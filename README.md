# PulsePlay

[**⬇ Скачать установщик для Windows**](https://github.com/oleg55553/PulsePlay/releases/download/latest/PulsePlay-Setup.exe) · [Описание выпуска](https://github.com/oleg55553/PulsePlay/releases/tag/latest)

PulsePlay is a Windows app with its own host and guest streaming system. It does
not launch Sunshine or Moonlight.

## Current alpha scope

- In-app host and guest screens.
- Direct signaling and encrypted WebRTC media over the Radmin VPN network.
- Full-desktop or selected-window capture, host system-audio loopback, guest
  volume/mute, and keyboard/mouse input.
- One guest at a time. No relay server or account service.

This is version 0.9.0-alpha1. Local connection, screen video, and audio output
have been checked. A connection between two separate computers still needs
verification. Gamepad forwarding, hardware video encoding, reconnection, and
network adaptation are still outstanding. Do not send an invite to someone you
do not trust: the invite grants control of the host keyboard and mouse until
streaming stops.

## Connecting two computers

1. Install and connect both computers to the same Radmin VPN network.
2. Start PulsePlay on the gaming computer. Open **Мой компьютер**, check the
   detected Radmin address, and click **Начать трансляцию**.
3. Copy the invitation and send the full text to the guest privately.
4. On the guest computer open **Подключиться**, paste the invite, and connect.
5. If Windows Firewall asks, allow PulsePlay on the Radmin/private network only.
6. The guest can control keyboard/mouse, adjust local audio volume, mute, or
   disconnect from the in-app viewer.

Stopping the host revokes the current invite. Start a new stream to create a new
invite. Both computers need the new PulsePlay build; old `PP1:` invitations from
the Sunshine/Moonlight version are not compatible.

## Development

Use Python 3.12 on Windows. Install `requirements-streaming.txt`, then run
`python app.py`. Build the standalone installer with `Build-Windows.bat` and
Inno Setup 6. The GitHub Actions Windows workflow uses the same dependency list.

## Release status

The Windows installer is available from the download link at the top of this
page. Both computers need PulsePlay and Radmin VPN connected to the same Radmin
network. Remote play between separate computers has not yet been verified.
