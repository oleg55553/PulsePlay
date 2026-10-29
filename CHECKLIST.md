# PulsePlay native-stream release checks

The built-in stream is still alpha. Do not publish it as a stable replacement
until all required checks below pass on real Windows computers.

## Build and start

- [ ] Install the pinned Python version and `requirements-streaming.txt` on a
  clean Windows x64 runner.
- [ ] Build `PulsePlay.exe` and `PulsePlay-Setup.exe` with the CI workflow.
- [ ] Install without Python, Sunshine, or Moonlight on a clean Windows 10/11 PC.
- [ ] Confirm no setup prompt tries to find/install Sunshine or Moonlight.

## Same Radmin VPN network

- [ ] Host finds only its Radmin VPN address and starts listening on port 47333.
- [ ] Guest rejects malformed invites and connects with the full `PP2:` invite.
- [ ] Invalid/revoked invites are rejected; host accepts one guest at a time.
- [ ] Firewall prompt allows operation over the VPN interface.
- [ ] Measure video smoothness, CPU/GPU usage, and interaction delay at 720p/30.
- [ ] Confirm system sound reaches the guest; test mute and volume at 0/50/100%.
- [ ] Test keyboard, mouse buttons, movement, and wheel; disconnect releases keys.
- [ ] Stop host and confirm old invite can no longer connect.
- [ ] Test two simultaneous guests are handled safely.
- [ ] Test disconnect during startup, during video, and while audio device changes.

## Privacy and scope

- [ ] Verify whole-desktop and selected-window capture on real Windows builds.
- [ ] Cover the selected window with unrelated windows and verify they never appear in the guest stream.
- [ ] Check invite handling/logs do not persist or print the access token.
- [ ] Review Windows firewall exposure and the UDP ports WebRTC negotiates.
- [ ] Test from different cities while both computers are in the same Radmin VPN.
- [ ] Test unsupported / not-installed Radmin cases show a clear explanation.

## Still planned

- [ ] Gamepad forwarding and a per-session consent/stop control for the host.
- [ ] Hardware H.264 encoding and adaptive bitrate / recovery.
- [ ] Per-monitor capture and display scaling.
