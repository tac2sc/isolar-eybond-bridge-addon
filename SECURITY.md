# Security

The EyeBond TCP/UDP protocol has no authentication or encryption. Run this
app on a trusted home network. UDP discovery on 58899 must not be exposed
to the Internet. FC4 forwards arbitrary serial bytes, including writes;
configure write permissions in EyeBond Local. This app is not a write firewall.

With a configured HA IPv4 endpoint, remote redirects are rejected by default.
With an empty endpoint, discovery accepts only an IPv4 target matching the UDP
sender; the first accepted target is pinned until restart. This is not protection
against a hostile host or source-address spoofing on the local network.

Host networking is retained for EyeBond broadcast discovery/callback compatibility.
UART access is required. There is no Supervisor API, Docker API, full_access,
host filesystem or elevated capability access. Default AppArmor confinement stays
enabled; a custom profile is intentionally not claimed without HAOS validation.

Report vulnerabilities using GitHub's private vulnerability reporting once enabled
by the repository owner. Do not publish sensitive packet captures in public issues.
Supported candidate: 0.2.x. Enable private reports before the first public release.
