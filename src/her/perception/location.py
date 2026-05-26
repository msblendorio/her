"""User-location resolution.

Three providers, tried in priority order:

1. **macOS Core Location** — accurate to city/neighbourhood via Wi-Fi
   triangulation. Native, no API key. Worker-thread friendly: we drive
   NSRunLoop manually so delegate callbacks fire off the main thread.

   **Important TCC caveat.** Apple gates Location Services behind an
   ``Info.plist`` key (``NSLocationUsageDescription``). A plain Python
   binary launched from a terminal does *not* have one, so the system
   keeps ``authorizationStatus`` at ``notDetermined`` forever and the
   permission dialog never appears. The cleanest unblock is to install
   ``CoreLocationCLI`` once (``brew install corelocationcli``); running
   it prompts the terminal app for permission, after which ALL command-
   line processes spawned from that terminal (including this one)
   inherit the grant and Core Location starts answering. Without that
   bootstrap, this provider silently falls through to IP geolocation.

2. **IP geolocation** (ipapi.co) — fallback when Core Location is
   denied/unavailable or we are not on macOS. Coarse (often wrong by
   100s of km on mobile carriers).
3. **System timezone** — final offline fallback handled by the caller.

The result is cached process-wide. Callers should invoke `detect_location()`;
the per-provider functions are exposed mostly for diagnostics/tests.
"""
from __future__ import annotations

import logging
import sys
import threading
import time

import httpx

log = logging.getLogger(__name__)

# Sentinel: None = not attempted yet; empty dict = attempted and failed,
# don't retry within this process; populated dict = success.
_CORE_CACHE: dict[str, str] | None = None
_IP_CACHE: dict[str, str] | None = None
_RESOLVE_LOCK = threading.Lock()


def detect_location_via_ip(timeout: float = 2.0) -> dict[str, str] | None:
    """Resolve approximate (city, region, country) via ipapi.co."""
    global _IP_CACHE
    if _IP_CACHE is not None:
        return _IP_CACHE or None
    try:
        r = httpx.get("https://ipapi.co/json/", timeout=timeout)
        r.raise_for_status()
        data = r.json()
        city = (data.get("city") or "").strip()
        region = (data.get("region") or "").strip()
        country = (data.get("country_name") or "").strip()
        if not (city or country):
            raise ValueError("ipapi returned no usable fields")
        _IP_CACHE = {"city": city, "region": region, "country": country}
        log.info("location[ip]: %s, %s, %s", city, region, country)
        return _IP_CACHE
    except Exception as e:
        log.debug("location[ip]: failed (%s)", e)
        _IP_CACHE = {}
        return None


def detect_location_via_corelocation(timeout: float = 6.0) -> dict[str, str] | None:
    """Resolve location via Apple Core Location (macOS only).

    On the first call macOS shows a TCC permission prompt for the Python
    binary. If granted, future runs use the cached authorization. On
    denial or non-macOS this returns ``None`` immediately on the next
    call (failure is cached for the lifetime of the process).
    """
    global _CORE_CACHE
    if _CORE_CACHE is not None:
        return _CORE_CACHE or None
    if sys.platform != "darwin":
        _CORE_CACHE = {}
        return None
    try:
        result = _resolve_corelocation_blocking(timeout)
    except ImportError as e:
        log.info("location[core]: pyobjc-framework-CoreLocation not installed (%s)", e)
        result = None
    except Exception:
        log.exception("location[core]: unexpected failure")
        result = None
    _CORE_CACHE = result or {}
    if result:
        log.info("location[core]: %s, %s, %s",
                 result.get("city"), result.get("region"), result.get("country"))
    return result


def detect_location(timeout: float = 6.0) -> tuple[dict[str, str] | None, str]:
    """Return ``(location, source)`` from the best available provider.

    ``source`` is ``"core"`` (Apple Core Location, accurate), ``"ip"``
    (geolocalization via ipapi.co, coarse), or ``""`` if no provider
    succeeded. Thread-safe and idempotent: subsequent calls hit the
    cache.
    """
    with _RESOLVE_LOCK:
        loc = detect_location_via_corelocation(timeout=timeout)
        if loc:
            return loc, "core"
        loc = detect_location_via_ip()
        if loc:
            return loc, "ip"
        return None, ""


def _resolve_corelocation_blocking(timeout: float) -> dict[str, str] | None:
    """Run CLLocationManager + reverse-geocode synchronously.

    Manually pumps NSRunLoop on the current thread so the manager's
    delegate callbacks fire from this thread (no main run loop needed —
    important since we are called from ``asyncio.to_thread`` workers).
    """
    # PyObjC imports are scoped so a missing framework doesn't blow up at
    # module load time on machines without CoreLocation installed.
    import CoreLocation  # type: ignore[import-not-found]
    import objc  # type: ignore[import-not-found]
    from Foundation import (  # type: ignore[import-not-found]
        NSDate,
        NSDefaultRunLoopMode,
        NSObject,
        NSRunLoop,
    )

    class _Delegate(NSObject):
        def init(self):
            self = objc.super(_Delegate, self).init()
            if self is None:
                return None
            self.placemark = None
            self.error = None
            self.done = False
            self._geocoding = False
            return self

        # CLLocationManagerDelegate ------------------------------------
        def locationManager_didUpdateLocations_(self, manager, locations):
            if not locations or self._geocoding:
                return
            self._geocoding = True
            manager.stopUpdatingLocation()
            self._reverse_geocode(locations[-1])

        def locationManager_didFailWithError_(self, manager, error):
            self.error = str(error)
            self.done = True

        def locationManagerDidChangeAuthorization_(self, manager):
            status = manager.authorizationStatus()
            # 3=AuthorizedAlways, 4=AuthorizedWhenInUse
            if status in (3, 4):
                manager.startUpdatingLocation()
            elif status == 2:  # Denied
                self.error = "denied"
                self.done = True
            # status 0/1 (notDetermined/restricted) — keep waiting

        # CLGeocoder completion handler --------------------------------
        def _reverse_geocode(self, location):
            geocoder = CoreLocation.CLGeocoder.alloc().init()

            def handler(placemarks, err):
                if placemarks is not None and len(placemarks) > 0:
                    self.placemark = placemarks[0]
                else:
                    self.error = str(err) if err else "no_placemark"
                self.done = True

            geocoder.reverseGeocodeLocation_completionHandler_(location, handler)

    # Quick exit if Location Services are off system-wide.
    if not CoreLocation.CLLocationManager.locationServicesEnabled():
        log.info(
            "location[core]: Location Services are disabled system-wide "
            "(System Settings → Privacy & Security → Location Services)"
        )
        return None

    manager = CoreLocation.CLLocationManager.alloc().init()
    delegate = _Delegate.alloc().init()
    manager.setDelegate_(delegate)
    manager.setDesiredAccuracy_(CoreLocation.kCLLocationAccuracyHundredMeters)

    manager.requestWhenInUseAuthorization()
    status = manager.authorizationStatus()
    if status == 2:  # Denied
        log.info(
            "location[core]: authorization denied. Allow your terminal or "
            "Python binary in System Settings → Privacy & Security → "
            "Location Services."
        )
        return None
    if status in (3, 4):
        manager.startUpdatingLocation()

    deadline = time.monotonic() + timeout
    rl = NSRunLoop.currentRunLoop()
    while not delegate.done and time.monotonic() < deadline:
        rl.runMode_beforeDate_(
            NSDefaultRunLoopMode,
            NSDate.dateWithTimeIntervalSinceNow_(0.2),
        )

    manager.stopUpdatingLocation()

    if delegate.error:
        log.info("location[core]: %s", delegate.error)
        return None
    pm = delegate.placemark
    if pm is None:
        # Most common cause: no TCC dialog ever appeared because the
        # Python interpreter has no Info.plist with
        # NSLocationUsageDescription. Falls through to the IP provider.
        log.info(
            "location[core]: no fix within %.1fs (status=%d). If you want "
            "accurate location, grant your terminal app Location Services "
            "access in System Settings.",
            timeout, status,
        )
        return None

    city = str(pm.locality() or "") or str(pm.subLocality() or "")
    region = str(pm.administrativeArea() or "")
    country = str(pm.country() or "")
    if not (city or country):
        return None
    return {"city": city, "region": region, "country": country}
