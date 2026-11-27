/** @odoo-module **/

// Internal users: Odoo's own red/green check-in/out dot opens the SAME face-detection
// dialog as the portal button (same messages, timings, location handling and selfie upload).
import { ActivityMenu } from "@hr_attendance/components/attendance_menu/attendance_menu";
import { patch } from "@web/core/utils/patch";

const LIB_URL = "/portal_attendance_face_recog_aretx/static/lib/face-api/";
const DETECT_INTERVAL_MS = 1000;  // wait before each detection attempt
const FACE_HITS_REQUIRED = 3;     // consecutive detections before submitting
const MISSES_BEFORE_ERROR = 3;    // consecutive misses before "can't detect face"
const RPC_TIMEOUT_MS = 30000;
const AUTO_CLOSE_MS = 3000;       // dialog closes this long after a successful submit

const COLORS = { ok: "#198754", err: "#dc3545", info: "#6c757d" };

function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

async function rpc(url, params) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), RPC_TIMEOUT_MS);
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
    detectorPromise = (async () => {
        if (!window.faceapi) {
            await new Promise((resolve, reject) => {
                const script = document.createElement("script");
                script.src = LIB_URL + "face-api.js";
                script.onload = resolve;
                script.onerror = () => reject(new Error("Could not load the face detector."));
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
    detectorPromise.catch(() => { detectorPromise = null; });
    return detectorPromise;
}

// Same markup as the portal overlay (views/attendence_views.xml).
function buildOverlay() {
    const overlay = document.createElement("div");
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.className = "d-print-none";
    overlay.style.cssText =
        "position:fixed; top:0; right:0; bottom:0; left:0; z-index:20000; background:rgba(0,0,0,0.6);";
    overlay.innerHTML =
        '<div class="d-flex align-items-center justify-content-center h-100 p-3">' +
        '<div class="card shadow" style="width:100%; max-width:420px;">' +
        '<div class="card-body text-center">' +
        '<h5 class="card-title mb-3">' +
        '<span class="pa_title">Attendance</span> ' +
        '<small class="text-muted pa_employee_name"></small>' +
        "</h5>" +
        '<div class="mb-3">' +
        '<video class="pa_video" autoplay playsinline muted ' +
        'style="display:none; width:100%; max-width:360px; border-radius:8px; border:4px solid transparent; transform:scaleX(-1);"></video>' +
        '<canvas class="pa_canvas" style="display:none;"></canvas>' +
        "</div>" +
        '<div class="pa_message fw-bold mb-3"></div>' +
        '<div class="d-flex justify-content-center gap-2">' +
        '<button type="button" class="pa_retry_btn btn btn-primary" style="display:none;">Try Again</button>' +
        '<button type="button" class="pa_close_btn btn btn-secondary">Close</button>' +
        "</div>" +
        "</div></div></div>";
    return overlay;
}

// Opens the dialog and runs the whole flow. Resolves when the dialog is closed.
function openAttendanceDialog(menu) {
    const overlay = buildOverlay();
    document.body.appendChild(overlay);

    const video = overlay.querySelector(".pa_video");
    const canvas = overlay.querySelector(".pa_canvas");
    const messageEl = overlay.querySelector(".pa_message");
    const nameEl = overlay.querySelector(".pa_employee_name");
    const titleEl = overlay.querySelector(".pa_title");
    const retryBtn = overlay.querySelector(".pa_retry_btn");
    const closeBtn = overlay.querySelector(".pa_close_btn");

    let stream = null;
    let watchId = null;
    let position = null;      // latest coords from watchPosition
    let session = 0;          // bumped on open/close to cancel stale async work
    let opening = false;
    let submitting = false;
    let finishedOk = false;
    let checkedIn = !!menu.state.checkedIn;
    let autoCloseTimer = null;
    let resolveClosed;
    const closed = new Promise((resolve) => { resolveClosed = resolve; });

    function showMessage(text, kind) {
        messageEl.textContent = text || "";
        messageEl.style.color = COLORS[kind || "info"];
    }

    function setFrame(kind) {
        video.style.borderColor = kind ? COLORS[kind] : "transparent";
    }

    function updateTitle() {
        titleEl.textContent = checkedIn ? "Check out" : "Check in";
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
            stream.getTracks().forEach((t) => t.stop());
            stream = null;
        }
        video.srcObject = null;
        video.style.display = "none";
        setFrame(null);
        updateButtons();
    }

    function onKeyDown(ev) {
        if (ev.key === "Escape") {
            closeOverlay();
        }
    }

    function closeOverlay() {
        if (submitting) {
            return;
        }
        clearTimeout(autoCloseTimer);
        closeCamera();
        document.removeEventListener("keydown", onKeyDown);
        window.removeEventListener("pagehide", closeCamera);
        overlay.remove();
        resolveClosed();
    }

    function startLocationTracking(sid) {
        position = null;
        watchId = navigator.geolocation.watchPosition(
            (pos) => {
                if (sid === session) {
                    position = pos.coords;
                }
            },
            (err) => {
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
                // Flip Odoo's red/green dot right away, then sync the rest from the server.
                menu.state.checkedIn = checkedIn;
                menu.searchReadEmployee().catch(() => {});
                updateTitle();
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
                media.getTracks().forEach((t) => t.stop());
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
    retryBtn.addEventListener("click", () => openCamera());
    closeBtn.addEventListener("click", closeOverlay);
    document.addEventListener("keydown", onKeyDown);
    window.addEventListener("pagehide", closeCamera);

    updateTitle();
    updateButtons();
    // Employee name next to the title, same as the portal dialog.
    rpc("/portal_attendance/status")
        .then((status) => {
            if (status && status.has_employee) {
                nameEl.textContent = "- " + status.employee_name;
            }
        })
        .catch(() => { /* name is cosmetic */ });

    openCamera();
    return closed;
}

// Odoo's own check-in/out dot now opens the same dialog as the portal button.
patch(ActivityMenu.prototype, {
    async signInOut() {
        // Prevent repeated clicks from opening multiple dialogs.
        if (this.paFaceCheckRunning) {
            return;
        }
        this.paFaceCheckRunning = true;
        try {
            this.dropdown.close();
            await openAttendanceDialog(this);
        } finally {
            this.paFaceCheckRunning = false;
        }
    },
});