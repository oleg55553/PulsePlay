"""PulsePlay's built-in WebRTC desktop stream (no Sunshine or Moonlight)."""
from __future__ import annotations

import asyncio
import base64
import fractions
import ipaddress
import os
import json
import queue
import secrets
import threading
import time
from dataclasses import dataclass


SIGNAL_PORT = 47333
MAX_SIGNAL_BYTES = 1_000_000


def list_windows() -> list[tuple[int, str]]:
    """List visible top-level windows except PulsePlay itself."""
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    current_pid = kernel32.GetCurrentProcessId()
    user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                                       wintypes.LPARAM), wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    windows = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length < 1:
            return True
        title_buffer = ctypes.create_unicode_buffer(min(length + 1, 512))
        user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        title = title_buffer.value.strip()
        if title and pid.value != current_pid:
            windows.append((int(hwnd), f"{title[:100]}  •  {pid.value}"))
        return True

    if not user32.EnumWindows(visit, 0):
        raise OSError(ctypes.get_last_error(), "Не удалось получить список окон Windows")
    return sorted(windows, key=lambda item: item[1].casefold())


def create_invite(host: str, token: str) -> str:
    """Encode a short-lived, host-authorized PulsePlay invitation."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("Для подключения хосту нужен IPv4-адрес Radmin VPN.") from exc
    if address.version != 4 or address.is_unspecified or address.is_loopback:
        raise ValueError("Укажи IPv4-адрес адаптера Radmin VPN.")
    body = json.dumps({"v": 2, "host": host, "port": SIGNAL_PORT, "token": token},
                      separators=(",", ":")).encode("utf-8")
    return "PP2:" + base64.urlsafe_b64encode(body).decode("ascii").rstrip("=")


def parse_invite(value: str) -> dict:
    value = value.strip()
    if not value.startswith("PP2:") or len(value) > 2048:
        raise ValueError("Вставь приглашение PulsePlay нового формата (начинается с PP2:).")
    try:
        raw = base64.b64decode(value[4:] + "=" * (-len(value[4:]) % 4),
                               altchars=b"-_", validate=True)
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Приглашение повреждено.") from exc
    if (not isinstance(data, dict) or data.get("v") != 2
            or not isinstance(data.get("host"), str)
            or not isinstance(data.get("port"), int)
            or not isinstance(data.get("token"), str)
            or len(data["token"]) < 32):
        raise ValueError("В приглашении не хватает адреса или ключа доступа.")
    try:
        address = ipaddress.ip_address(data["host"])
    except ValueError as exc:
        raise ValueError("В приглашении указан неверный адрес компьютера.") from exc
    if address.version != 4 or address.is_unspecified or address.is_loopback:
        raise ValueError("В приглашении указан неверный адрес Radmin VPN.")
    return data


def _wire_json(value: dict) -> bytes:
    data = json.dumps(value, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_SIGNAL_BYTES:
        raise ValueError("Слишком большой запрос подключения.")
    return data + b"\n"


async def _read_json(reader: asyncio.StreamReader) -> dict:
    line = await asyncio.wait_for(reader.readline(), timeout=20)
    if not line or len(line) > MAX_SIGNAL_BYTES:
        raise ValueError("Гость прислал пустой или слишком большой запрос.")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise ValueError("Неверный формат запроса.")
    return value


class DesktopTrack:
    """Create the actual aiortc video track lazily on Windows."""

    def __new__(cls, *args, **kwargs):
        try:
            import dxcam
            from aiortc import VideoStreamTrack
            from av import VideoFrame
        except ImportError as exc:
            raise RuntimeError("Встроенный видеомодуль не установлен в этой сборке PulsePlay.") from exc

        class _Track(VideoStreamTrack):
            kind = "video"

            def __init__(self, fps=30, window_hwnd=None):
                super().__init__()
                self.camera = None
                self.capture = None
                self.capture_control = None
                self.closed = threading.Event()
                self.window_frames = queue.Queue(maxsize=1)
                self.last_window_frame = None
                if window_hwnd is None:
                    self.camera = dxcam.create(output_color="BGRA", processor_backend="numpy")
                    self.camera.start(target_fps=fps, video_mode=True)
                else:
                    try:
                        from windows_capture import WindowsCapture
                    except ImportError as exc:
                        raise RuntimeError("Модуль выбора окна Windows отсутствует в этой сборке.") from exc
                    capture = WindowsCapture(cursor_capture=True, draw_border=False,
                                             window_hwnd=int(window_hwnd),
                                             minimum_update_interval=max(1, 1000 // fps),
                                             dirty_region=False)

                    @capture.event
                    def on_frame_arrived(frame, _capture_control):
                        pixels = frame.frame_buffer.copy()
                        if self.window_frames.full():
                            try:
                                self.window_frames.get_nowait()
                            except queue.Empty:
                                pass
                        try:
                            self.window_frames.put_nowait(pixels)
                        except queue.Full:
                            pass

                    @capture.event
                    def on_closed():
                        self.closed.set()

                    self.capture = capture
                    self.capture_control = capture.start_free_threaded()

            async def recv(self):
                pts, time_base = await self.next_timestamp()
                if self.camera is not None:
                    frame = await asyncio.to_thread(self.camera.get_latest_frame)
                    if frame is None:
                        await asyncio.sleep(0.005)
                        frame = await asyncio.to_thread(self.camera.get_latest_frame)
                else:
                    if self.closed.is_set() and self.window_frames.empty():
                        raise RuntimeError("Выбранное окно закрыто. Останови и запусти трансляцию снова.")
                    try:
                        self.last_window_frame = self.window_frames.get_nowait()
                    except queue.Empty:
                        if self.last_window_frame is None:
                            self.last_window_frame = await asyncio.to_thread(
                                self.window_frames.get, True, 5)
                    frame = self.last_window_frame
                if frame is None:
                    raise RuntimeError("Windows не вернула кадр экрана.")
                video = VideoFrame.from_ndarray(frame, format="bgra")
                video.pts, video.time_base = pts, time_base
                return video

            def stop(self):
                try:
                    if self.camera is not None:
                        self.camera.stop()
                        self.camera.release()
                    if self.capture_control is not None:
                        self.capture_control.stop()
                        self.capture_control.wait()
                finally:
                    super().stop()

        return _Track(*args, **kwargs)


class LoopbackTrack:
    """WASAPI loopback audio source, exposed as an aiortc audio track."""

    def __new__(cls, *args, **kwargs):
        try:
            import numpy as np
            import soundcard as sc
            from aiortc import AudioStreamTrack
            from av import AudioFrame
        except ImportError as exc:
            raise RuntimeError("Встроенный модуль передачи звука не установлен.") from exc

        class _Track(AudioStreamTrack):
            kind = "audio"

            def __init__(self):
                super().__init__()
                speaker = sc.default_speaker()
                self.loopback = sc.get_microphone(speaker.name, include_loopback=True)
                self.recorder = self.loopback.recorder(samplerate=48000, blocksize=960)
                self.recorder.__enter__()
                self.timestamp = 0

            async def recv(self):
                block = await asyncio.to_thread(self.recorder.record, numframes=960)
                if block.ndim != 2 or block.shape[1] == 0:
                    raise RuntimeError("Аудиоустройство не вернуло звуковые данные.")
                if block.shape[1] == 1:
                    block = np.repeat(block, 2, axis=1)
                elif block.shape[1] > 2:
                    block = block[:, :2]
                pcm = np.clip(block.T * 32767, -32768, 32767).astype(np.int16)
                audio = AudioFrame.from_ndarray(np.ascontiguousarray(pcm),
                                                format="s16p", layout="stereo")
                audio.sample_rate = 48000
                audio.pts = self.timestamp
                audio.time_base = fractions.Fraction(1, 48000)
                self.timestamp += audio.samples
                return audio

            def stop(self):
                try:
                    self.recorder.__exit__(None, None, None)
                finally:
                    super().stop()

        return _Track()


def _inject_remote_input(message: str, held_keys: set[int], held_buttons: set[str],
                         window_hwnd: int | None = None) -> None:
    """Allow only a small, validated set of remote keyboard and mouse events."""
    try:
        import ctypes
        from ctypes import wintypes
        if len(message) > 512:
            return
        item = json.loads(message)
        if not isinstance(item, dict):
            return
        user32 = ctypes.windll.user32
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        if window_hwnd is not None:
            if not user32.IsWindow(window_hwnd):
                return
            user32.SetForegroundWindow(window_hwnd)
        if item.get("type") == "key":
            vk = item.get("vk")
            down = item.get("down")
            if type(vk) is int and 1 <= vk <= 254 and type(down) is bool:
                user32.keybd_event(vk, 0, 0 if down else 0x0002, 0)
                if down:
                    held_keys.add(vk)
                else:
                    held_keys.discard(vk)
        elif item.get("type") == "mouse":
            x, y = item.get("x"), item.get("y")
            if (type(x) in (int, float) and type(y) in (int, float)
                    and 0 <= x <= 1 and 0 <= y <= 1):
                if window_hwnd is not None:
                    rect = wintypes.RECT()
                    point = wintypes.POINT()
                    if user32.GetClientRect(window_hwnd, ctypes.byref(rect)):
                        point.x = round(x * max(0, rect.right - rect.left - 1))
                        point.y = round(y * max(0, rect.bottom - rect.top - 1))
                        if user32.ClientToScreen(window_hwnd, ctypes.byref(point)):
                            user32.SetCursorPos(point.x, point.y)
                elif window_hwnd is None:
                    width, height = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
                    user32.SetCursorPos(round(x * max(0, width - 1)),
                                        round(y * max(0, height - 1)))
                button = item.get("button")
                flags = {"left-down": 0x0002, "left-up": 0x0004,
                         "right-down": 0x0008, "right-up": 0x0010,
                         "middle-down": 0x0020, "middle-up": 0x0040}
                if button in flags:
                    user32.mouse_event(flags[button], 0, 0, 0, 0)
                    if button.endswith("-down"):
                        held_buttons.add(button.split("-", 1)[0])
                    else:
                        held_buttons.discard(button.split("-", 1)[0])
                elif button == "wheel-up":
                    user32.mouse_event(0x0800, 0, 0, 120, 0)
                elif button == "wheel-down":
                    user32.mouse_event(0x0800, 0, 0, -120, 0)
    except (ValueError, OSError, TypeError, AttributeError):
        return


def _release_remote_input(held_keys: set[int], held_buttons: set[str]) -> None:
    try:
        import ctypes
        user32 = ctypes.windll.user32
        for vk in tuple(held_keys):
            user32.keybd_event(vk, 0, 0x0002, 0)
        for button in tuple(held_buttons):
            flag = {"left": 0x0004, "right": 0x0010,
                    "middle": 0x0040}.get(button)
            if flag:
                user32.mouse_event(flag, 0, 0, 0, 0)
    except (OSError, AttributeError):
        pass
    held_keys.clear()
    held_buttons.clear()


@dataclass
class StreamEvent:
    kind: str
    value: object = None


class NativeStream:
    """Thread-safe host/client controller. Signaling is confined to Radmin/LAN."""

    def __init__(self, events: queue.Queue | None = None):
        self.events = events or queue.Queue()
        self.loop = None
        self._loop_ready = threading.Event()
        self._loop_error = None
        self.thread = threading.Thread(target=self._run_loop,
                                       name="PulsePlay-WebRTC", daemon=True)
        self.thread.start()
        timer = threading.Timer(8, self._report_loop_timeout)
        timer.daemon = True
        timer.start()
        self._future = None
        self._token = None
        self._capture_hwnd = None
        self._peer = None
        self._server = None
        self._tracks = []
        self._session_task = None
        self._video_frames = queue.Queue(maxsize=1)
        self._input_channel = None
        self._held_keys: set[int] = set()
        self._held_buttons: set[str] = set()
        self._muted = False
        self._volume = 1.0
        self._session_done = None

    def _run_loop(self):
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self._loop_ready.set()
            self.loop.run_forever()
        except Exception as exc:
            self._loop_error = exc
            self._loop_ready.set()
            self._event("error", f"Не удалось запустить сетевой модуль: {exc}")

    def _report_loop_timeout(self):
        if not self._loop_ready.is_set():
            self._event("loop_timeout")

    def _require_loop(self):
        if not self._loop_ready.is_set():
            raise RuntimeError("Сетевой модуль ещё запускается. Подожди немного и нажми ещё раз.")
        if self._loop_error is not None or self.loop is None or not self.loop.is_running():
            raise RuntimeError(f"Сетевой модуль не запустился: {self._loop_error or 'цикл остановлен'}")

    def _event(self, kind, value=None):
        self.events.put(StreamEvent(kind, value))

    def start_host(self, address: str, fps=30, window_hwnd=None):
        self._require_loop()
        if self._future and not self._future.done():
            raise RuntimeError("Трансляция PulsePlay уже запущена.")
        self._token = secrets.token_urlsafe(32)
        self._capture_hwnd = window_hwnd
        self._future = asyncio.run_coroutine_threadsafe(self._host(address, fps), self.loop)
        return create_invite(address, self._token)

    async def _host(self, address: str, fps):
        self._session_task = asyncio.current_task()
        try:
            self._tracks = []
            self._tracks.append(DesktopTrack(fps, self._capture_hwnd))
            self._tracks.append(LoopbackTrack())
            self._server = await asyncio.start_server(self._accept, "0.0.0.0", SIGNAL_PORT,
                                                       limit=MAX_SIGNAL_BYTES)
            self._event("host_started", address)
            async with self._server:
                await self._server.serve_forever()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._event("error", str(exc))
        finally:
            server, self._server = self._server, None
            if server is not None:
                server.close()
                await server.wait_closed()
            await self._close_peer()
            for track in self._tracks:
                track.stop()
            self._tracks.clear()
            self._session_task = None
            self._event("stopped")

    async def _accept(self, reader, writer):
        if self._peer is not None:
            writer.write(_wire_json({"error": "К этому хосту уже подключён другой гость."}))
            try:
                await writer.drain()
            except OSError:
                pass
            writer.close()
            await writer.wait_closed()
            return
        pc = None
        try:
            hello = await _read_json(reader)
            if not secrets.compare_digest(str(hello.get("token", "")), self._token or ""):
                raise ValueError("Приглашение неверное или уже отозвано.")
            offer = hello.get("offer")
            if not isinstance(offer, dict) or offer.get("type") != "offer" or not isinstance(offer.get("sdp"), str):
                raise ValueError("Гость прислал неверное SDP-предложение.")
            from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
            pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
            self._peer = pc
            for track in self._tracks:
                pc.addTrack(track)

            @pc.on("datachannel")
            def on_datachannel(channel):
                self._input_channel = channel

                @channel.on("message")
                def on_message(message):
                    if isinstance(message, str):
                        _inject_remote_input(message, self._held_keys,
                                             self._held_buttons, self._capture_hwnd)

            @pc.on("connectionstatechange")
            async def on_state():
                self._event("connection", pc.connectionState)
                if pc.connectionState in ("failed", "closed"):
                    await self._close_peer()

            await pc.setRemoteDescription(RTCSessionDescription(sdp=offer["sdp"], type="offer"))
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
            writer.write(_wire_json({"answer": {"type": pc.localDescription.type,
                                                "sdp": pc.localDescription.sdp}}))
            await writer.drain()
            self._event("guest_signaling")
        except Exception as exc:
            self._event("error", str(exc))
            try:
                writer.write(_wire_json({"error": str(exc)[:1000]}))
                await writer.drain()
            except (OSError, RuntimeError, ValueError):
                pass
            if pc:
                await pc.close()
                if self._peer is pc:
                    self._peer = None
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    def connect_guest(self, invite: str):
        self._require_loop()
        if self._future and not self._future.done():
            raise RuntimeError("PulsePlay уже выполняет подключение.")
        data = parse_invite(invite)
        self._future = asyncio.run_coroutine_threadsafe(self._guest(data), self.loop)

    async def _guest(self, invite):
        self._session_task = asyncio.current_task()
        pc = None
        self._session_done = asyncio.Event()
        try:
            from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
            pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
            self._peer = pc
            pc.addTransceiver("video", direction="recvonly")
            pc.addTransceiver("audio", direction="recvonly")
            channel = pc.createDataChannel("input", ordered=True)
            self._input_channel = channel

            @pc.on("track")
            def on_track(track):
                if track.kind == "video":
                    asyncio.create_task(self._receive_video(track))
                elif track.kind == "audio":
                    asyncio.create_task(self._receive_audio(track))

            @pc.on("connectionstatechange")
            async def on_state():
                self._event("connection", pc.connectionState)
                if pc.connectionState == "failed":
                    await self._close_peer()

            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(invite["host"], invite["port"], limit=MAX_SIGNAL_BYTES), timeout=20)
            writer.write(_wire_json({"token": invite["token"],
                                     "offer": {"type": pc.localDescription.type,
                                               "sdp": pc.localDescription.sdp}}))
            await writer.drain()
            response = await _read_json(reader)
            writer.close()
            await writer.wait_closed()
            answer = response.get("answer")
            if not isinstance(answer, dict) or not isinstance(answer.get("sdp"), str):
                raise ValueError(str(response.get("error", "Хост не прислал ответ.")))
            await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"],
                                                                 type=answer["type"]))
            self._event("connecting")
            deadline = asyncio.get_running_loop().time() + 30
            while pc.connectionState not in ("connected", "failed", "closed"):
                if asyncio.get_running_loop().time() >= deadline:
                    raise TimeoutError("Гость не нашёл хост по Radmin VPN. Проверь общую сеть и брандмауэр Windows.")
                await asyncio.sleep(0.2)
            if pc.connectionState != "connected":
                raise ConnectionError("Не удалось установить медиасоединение. Проверь сеть Radmin VPN и правила брандмауэра.")
            session_done = self._session_done
            if session_done is not None:
                await session_done.wait()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._event("error", str(exc))
            if pc:
                await pc.close()
                if self._peer is pc:
                    self._peer = None
        finally:
            if pc is not None and self._peer is pc:
                await self._close_peer()
            self._session_task = None

    async def _receive_video(self, track):
        while True:
            try:
                frame = await track.recv()
                image = frame.to_image()
                if self._video_frames.full():
                    try:
                        self._video_frames.get_nowait()
                    except queue.Empty:
                        pass
                self._video_frames.put_nowait(image)
            except Exception:
                return

    async def _receive_audio(self, track):
        com_initialized = False
        try:
            # SoundCard creates its module level COM helper on the host's
            # asyncio thread.  Each Windows thread that uses WASAPI still
            # needs its own COM apartment; host and guest have separate loops.
            import ctypes
            ole32 = ctypes.OleDLL("ole32")
            ole32.CoInitializeEx.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
            ole32.CoInitializeEx.restype = ctypes.c_long
            ole32.CoUninitialize.argtypes = ()
            ole32.CoUninitialize.restype = None
            hr = ole32.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED
            if hr < 0:
                raise OSError(f"Не удалось включить WASAPI для звука: HRESULT 0x{hr & 0xffffffff:08X}")
            com_initialized = True
            import numpy as np
            import soundcard as sc
            speaker = sc.default_speaker()
            player = speaker.player(samplerate=48000, blocksize=960)
            with player:
                while True:
                    frame = await track.recv()
                    if self._muted:
                        continue
                    samples = frame.to_ndarray()
                    channels = max(1, len(frame.layout.channels))
                    if frame.format.is_planar:
                        samples = samples.T
                    else:
                        samples = samples.reshape(-1, channels)
                    if samples.shape[1] == 1:
                        samples = np.repeat(samples, 2, axis=1)
                    elif samples.shape[1] > 2:
                        samples = samples[:, :2]
                    audio = samples.astype(np.float32)
                    if np.issubdtype(samples.dtype, np.integer):
                        audio /= 32768.0
                    audio *= self._volume
                    # SoundCard's WASAPI player owns COM interfaces created
                    # above on this asyncio thread.  Calling it via
                    # asyncio.to_thread() moves those interfaces to a worker
                    # thread without COM initialization and fails with
                    # 0x800401f0 (CO_E_NOTINITIALIZED).
                    player.play(audio)
        except Exception as exc:
            self._event("audio_error", str(exc))
        finally:
            if com_initialized:
                ole32.CoUninitialize()

    def latest_video(self):
        try:
            return self._video_frames.get_nowait()
        except queue.Empty:
            return None

    def send_input(self, payload: dict):
        channel = self._input_channel
        if channel is not None and getattr(channel, "readyState", None) == "open":
            try:
                channel.send(json.dumps(payload, separators=(",", ":")))
            except Exception:
                pass

    def set_muted(self, value: bool):
        self._muted = bool(value)

    def set_volume(self, value):
        self._volume = max(0.0, min(1.0, float(value)))
        self._muted = self._volume == 0

    def stop(self):
        if self.loop is not None and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self._stop_session(), self.loop)

    async def _stop_session(self):
        task = self._session_task
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return
        await self._shutdown()

    async def _shutdown(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        await self._close_peer()
        for track in self._tracks:
            track.stop()
        self._tracks.clear()
        self._event("stopped")

    async def _close_peer(self):
        pc, self._peer = self._peer, None
        self._input_channel = None
        if pc:
            _release_remote_input(self._held_keys, self._held_buttons)
        if self._session_done is not None:
            self._session_done.set()
        if pc:
            await pc.close()


def create_stream(events=None) -> NativeStream:
    return NativeStream(events)
