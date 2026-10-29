"""Windows virtual-network discovery used by PulsePlay's direct sessions."""
import ipaddress
import os
import re
import subprocess


def _radmin_ip_from_ipconfig(output: str) -> str:
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if not re.search(r"Radmin\s+VPN", line, re.IGNORECASE):
            continue
        for adapter_line in lines[index + 1:index + 12]:
            match = re.search(r"IPv4[^:\r\n]*:\s*([0-9.]+)", adapter_line,
                              re.IGNORECASE)
            if not match:
                continue
            try:
                address = ipaddress.IPv4Address(match.group(1))
            except ipaddress.AddressValueError:
                continue
            if not address.is_unspecified and not address.is_loopback:
                return str(address)
    return ""


def radmin_vpn_address() -> str:
    """Return the Radmin VPN adapter's IPv4 address without internet lookup."""
    if os.name != "nt":
        return ""
    try:
        result = subprocess.run(
            ["ipconfig"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="mbcs", errors="replace",
            timeout=5, shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return _radmin_ip_from_ipconfig(result.stdout)
