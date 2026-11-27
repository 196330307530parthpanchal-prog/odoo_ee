(function () {
    "use strict";

    const LIB_URL = "/portal_attendance_face_recog_aretx/static/lib/face-api/";
    const DETECT_INTERVAL_MS = 1000;  // wait before each detection attempt
    const FACE_HITS_REQUIRED = 3;     // consecutive detections before submitting
    const MISSES_BEFORE_ERROR = 3;    // consecutive misses before "can't detect face"
    const RPC_TIMEOUT_MS = 30000;
    const AUTO_CLOSE_MS = 3000;       // overlay closes this long after a successful submit

    const COLORS = { ok: "#198754", err: "#dc3545", info: "#6c757d" };

    function ready(fn) {
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", fn);
        } else {
            fn();
        }
    }

    function sleep(ms) {
        return new Promise(function (resolve) { setTimeout(resolve, ms); });
    }

    async function rpc(url, params) {
        const controller = new AbortController();
        const timer = setTimeout(function () { controller.abort(); }, RPC_TIMEOUT_MS);
        try {
            const response = await fetch(url, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: params || {} }),
                signal: controller.signal,
            });
            if (!response.ok) {
                throw new Error("Server error (" + response.status + ")");
            }
            const data = await response.json();
            if (data.error) {
                throw new Error((data.error.data && data.error.data.message) || data.error.message || "Server error");
            }
            return data.result;
        } catch (err) {
            if (err.name === "AbortError") {
                throw new Error("The server took too long to respond. Please try again.");
            }
            throw err;
        } finally {
            clearTimeout(timer);
        }
    }

    // Face detector (detection only, no recognition). Loaded once, on first use.
    let detectorPromise = null;
    function loadDetector() {
        if (detectorPromise) {
            return detectorPromise;
        }
        detectorPromise = (async function () {
            if (!window.faceapi) {
                await new Promise(function (resolve, reject) {
                    const script = document.createElement("script");
                    script.src = LIB_URL + "face-api.js";
                    script.onload = resolve;
                    script.onerror = function () { reject(new Error("Could not load the face detector.")); };
                    document.head.appendChild(script);
                });
            }
            const faceapi = window.faceapi;
            let ok = false;
            try { ok = await faceapi.tf.setBackend("webgl"); } catch (e) { ok = false; }
            if (!ok) {
                await faceapi.tf.setBackend("cpu");
            }
            await faceapi.tf.ready();
            await faceapi.nets.tinyFaceDetector.loadFromUri(LIB_URL + "model");
        })();
        detectorPromise.catch(function () { detectorPromise = null; });
        return detectorPromise;
    }

    ready(function () {
        const overlay = document.getElementById("pa_overlay");
        const navItems = document.querySelectorAll(".o_pa_nav_item");
        if (!overlay || !navItems.length) {
            return;   // public visitor, or no navbar item on this page
        }
        const video = document.getElementById("pa_video");
        const canvas = document.getElementById("pa_canvas");
        const messageEl = document.getElementById("pa_message");
        const nameEl = document.getElementById("pa_employee_name");
        const titleEl = document.getElementById("pa_title");
        const retryBtn = document.getElementById("pa_retry_btn");
        const closeBtn = document.getElementById("pa_close_btn");

        let stream = null;
        let watchId = null;
        let position = null;      // latest coords from watchPosition
        let session = 0;          // bumped on open/close to cancel stale async work
        let opening = false;
        let submitting = false;
        let finishedOk = false;
        let checkedIn = false;
        let autoCloseTimer = null;

        function showMessage(text, kind) {
            messageEl.textContent = text || "";
            messageEl.style.color = COLORS[kind || "info"];
        }

        function setFrame(kind) {
            video.style.borderColor = kind ? COLORS[kind] : "transparent";
        }

        function updateNav() {
            navItems.forEach(function (item) {
                const btn = item.querySelector(".o_pa_nav_btn");
                const icon = item.querySelector(".o_pa_nav_icon");
                item.querySelector(".o_pa_nav_label").textContent = checkedIn ? "Check out" : "Check in";
                icon.className = "o_pa_nav_icon fa me-1 " + (checkedIn ? "fa-sign-out" : "fa-sign-in");
                btn.className = "o_pa_nav_btn btn btn-sm rounded-pill text-nowrap " +
                    (checkedIn ? "btn-warning" : "btn-success");
            });
            titleEl.textContent = checkedIn ? "Check out" : "Check in";
        }

        // Put the button beside the header search icon (desktop) or between the logo and
        // the hamburger (mobile/tablet); fall back to the navbar, then to a fixed corner.
        function placeNav(item) {
            const isMobile = window.matchMedia("(max-width: 991.98px)").matches;

            // Undo whatever the previous layout applied (needed when the window is resized).
            const oldWrap = item.closest("li.o_pa_nav_li");
            if (oldWrap) {
                oldWrap.replaceWith(item);   // drops the wrapper <li>, no empty leftovers
            }
            item.style.position = item.style.top = item.style.right =
                item.style.bottom = item.style.zIndex = "";
            item.classList.remove("ms-2", "me-3");

            if (isMobile) {
                // Logo -> [this slot] -> hamburger
                const slot = document.querySelector(
                    "header nav.o_header_mobile .o_header_mobile_buttons_wrap");
                if (slot) {
                    const li = document.createElement("li");
                    li.className = "nav-item o_pa_nav_li d-flex align-items-center";
                    li.appendChild(item);
                    slot.appendChild(li);
                    return;
                }
                // Custom header without the standard slot: float bottom-right.
                item.style.position = "fixed";
                item.style.right = "16px";
                item.style.bottom = "16px";
                item.style.zIndex = "1050";
                document.getElementById("wrapwrap").appendChild(item);
                return;
            }

            // Desktop (unchanged): place the button beside the search icon.
            const searchSelectors = [
                "header [data-bs-target='#o_search_modal']",
                "header .o_searchbar_form",
                "header .o_wsale_products_searchbar_form",
                "header form[action='/website/search']",
                "header .fa-search",
            ];
            for (const sel of searchSelectors) {
                let target = document.querySelector(sel);
                if (target) {
                    target = target.closest("li, .o_searchbar_form, form, a, button") || target;
                    item.classList.add("ms-2", "me-3", "d-inline-flex", "align-items-center");
                    target.parentNode.insertBefore(item, target);
                    return;
                }
            }
            const nav = document.querySelector("header #top_menu, header .navbar-nav");
            if (nav) {
                const li = document.createElement("li");
                li.className = "nav-item o_pa_nav_li d-flex align-items-center ms-2";
                li.appendChild(item);
                nav.appendChild(li);
                return;
            }
            item.style.position = "fixed";
            item.style.top = "12px";
            item.style.right = "12px";
            item.style.zIndex = "1050";
        }

        function updateButtons() {
            const idle = !stream && !opening && !submitting && !finishedOk;
            retryBtn.style.display = idle ? "" : "none";
            closeBtn.disabled = submitting;
        }

        // Stops camera AND location tracking, and cancels any running detection loop.
        function closeCamera() {
            session++;
            if (watchId !== null) {
                navigator.geolocation.clearWatch(watchId);
                watchId = null;
            }
            position = null;
            if (stream) {
                stream.getTracks().forEach(function (t) { t.stop(); });
                stream = null;
            }
            video.srcObject = null;
            video.style.display = "none";
            setFrame(null);
            updateButtons();
        }

        function closeOverlay() {
            if (submitting) {
                return;
            }
            clearTimeout(autoCloseTimer);
            closeCamera();
            overlay.style.display = "none";
            showMessage("", "info");
        }

        function startLocationTracking(sid) {
            position = null;
            watchId = navigator.geolocation.watchPosition(
                function (pos) {
                    if (sid === session) {
                        position = pos.coords;
                    }
                },
                function (err) {
                    if (sid !== session) {
                        return;
                    }
                    if (err.code === 1) {  // permission denied
                        showMessage("Location permission denied. Please allow location access and try again.", "err");
                        closeCamera();
                    }
                    // timeout / unavailable: watchPosition keeps trying, the loop keeps waiting
                },
                { enableHighAccuracy: true, maximumAge: 0, timeout: 20000 }
            );
        }

        function captureSelfie() {
            const vw = video.videoWidth;
            const vh = video.videoHeight;
            if (!vw || !vh) {
                throw new Error("The camera is not ready yet. Please try again.");
            }
            const scale = Math.min(1, 640 / vw);
            canvas.width = Math.round(vw * scale);
            canvas.height = Math.round(vh * scale);
            canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
            return canvas.toDataURL("image/jpeg", 0.85);
        }

        async function submitAttendance() {
            submitting = true;
            updateButtons();
            showMessage("Face detected. Submitting attendance...", "ok");
            try {
                const image = captureSelfie();
                const result = await rpc("/portal_attendance/submit", {
                    image: image,
                    latitude: position.latitude,
                    longitude: position.longitude,
                });
                if (result.success) {
                    finishedOk = true;
                    checkedIn = result.action === "check_in";
                    updateNav();
                    showMessage(result.message, "ok");
                    autoCloseTimer = setTimeout(closeOverlay, AUTO_CLOSE_MS);
                } else {
                    showMessage(result.message, "err");
                }
            } catch (err) {
                showMessage(err.message, "err");
            }
            submitting = false;
            closeCamera();   // stops the camera and the location tracking
        }

        async function detectLoop(sid) {
            const faceapi = window.faceapi;
            const options = new faceapi.TinyFaceDetectorOptions({ inputSize: 224, scoreThreshold: 0.5 });
            let hits = 0;
            let misses = 0;
            showMessage("Looking for your face...", "info");
            while (sid === session && stream) {
                await sleep(DETECT_INTERVAL_MS);
                if (sid !== session || !stream) {
                    return;
                }
                let face = null;
                try {
                    face = await faceapi.detectSingleFace(video, options);
                } catch (e) {
                    face = null;
                }
                if (sid !== session) {
                    return;
                }
                if (face) {
                    misses = 0;
                    hits++;
                    setFrame("ok");
                    if (hits < FACE_HITS_REQUIRED) {
                        showMessage("Face detected. Hold still...", "ok");
                    } else if (!position) {
                        showMessage("Face detected. Waiting for your location...", "ok");
                    } else {
                        await submitAttendance();
                        return;
                    }
                } else {
                    hits = 0;
                    misses++;
                    setFrame(misses >= MISSES_BEFORE_ERROR ? "err" : null);
                    if (misses >= MISSES_BEFORE_ERROR) {
                        showMessage("Can't detect face. Please look at the camera and make sure nothing covers it.", "err");
                    }
                }
            }
        }

        async function openCamera() {
            if (opening || submitting || stream) {
                return;
            }
            finishedOk = false;
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !navigator.geolocation) {
                showMessage("Camera or location is not available. Please use HTTPS and a supported browser.", "err");
                updateButtons();
                return;
            }
            const sid = ++session;
            opening = true;
            updateButtons();
            showMessage("Starting camera and location...", "info");

            // Camera and location tracking start together.
            startLocationTracking(sid);
            try {
                const media = await navigator.mediaDevices.getUserMedia({
                    video: { facingMode: "user" },
                    audio: false,
                });
                if (sid !== session) {   // closed while waiting for permission
                    media.getTracks().forEach(function (t) { t.stop(); });
                    opening = false;
                    return;
                }
                stream = media;
                video.srcObject = stream;
                video.style.display = "inline-block";
                try { await video.play(); } catch (e) { /* autoplay attribute handles it */ }
            } catch (err) {
                showMessage("Unable to access the camera: " + err.message, "err");
                opening = false;
                closeCamera();
                return;
            }
            opening = false;
            updateButtons();

            showMessage("Loading face detector...", "info");
            try {
                await loadDetector();
            } catch (err) {
                if (sid === session) {
                    showMessage(err.message, "err");
                    closeCamera();
                }
                return;
            }
            if (sid !== session) {
                return;
            }
            detectLoop(sid);
        }

        // ---- wiring
        navItems.forEach(function (item) {
            item.querySelector(".o_pa_nav_btn").addEventListener("click", function (ev) {
                ev.preventDefault();
                clearTimeout(autoCloseTimer);
                overlay.style.display = "";
                openCamera();
            });
        });
        retryBtn.addEventListener("click", function () { openCamera(); });
        closeBtn.addEventListener("click", closeOverlay);
        document.addEventListener("keydown", function (ev) {
            if (ev.key === "Escape" && overlay.style.display !== "none") {
                closeOverlay();
            }
        });
        window.addEventListener("pagehide", closeCamera);

        rpc("/portal_attendance/status")
            .then(function (status) {
                if (!status || !status.has_employee) {
                    return;   // user has no employee: navbar button stays hidden
                }
                checkedIn = !!status.checked_in;
                nameEl.textContent = "- " + status.employee_name;
                updateNav();
                updateButtons();
                navItems.forEach(function (item) { placeNav(item); item.style.display = ""; });
                window.matchMedia("(max-width: 991.98px)").addEventListener("change", function () {
                    navItems.forEach(function (item) { placeNav(item); });
                });
            })
            .catch(function () { /* leave the navbar button hidden */ });
    });
})();