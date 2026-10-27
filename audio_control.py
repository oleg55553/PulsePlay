"""Per-application Windows audio session volume control for the guest client."""


def set_process_volume(process_id, percent):
    """Set the Windows mixer volume for one process; return False until it has a session."""
    process_id = int(process_id)
    percent = max(0, min(100, int(percent)))
    from pycaw.pycaw import AudioUtilities

    for session in AudioUtilities.GetAllSessions():
        if session.ProcessId == process_id:
            session.SimpleAudioVolume.SetMasterVolume(percent / 100.0, None)
            return True
    return False
