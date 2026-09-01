function ipv4Octets(hostname: string): number[] | null {
    const match = hostname.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
    if (!match) return null;
    const octets = match.slice(1).map(Number);
    return octets.every((value) => Number.isInteger(value) && value >= 0 && value <= 255)
        ? octets
        : null;
}

export function isPrivateOrReservedIpv4Literal(hostname: string): boolean {
    const octets = ipv4Octets(hostname);
    if (!octets) return false;
    const [a, b, c] = octets;

    return a === 0
        || a === 10
        || a === 127
        || (a === 100 && b >= 64 && b <= 127)
        || (a === 169 && b === 254)
        || (a === 172 && b >= 16 && b <= 31)
        || (a === 192 && b === 0 && c === 0)
        || (a === 192 && b === 0 && c === 2)
        || (a === 192 && b === 88 && c === 99)
        || (a === 192 && b === 168)
        || (a === 198 && (b === 18 || b === 19))
        || (a === 198 && b === 51 && c === 100)
        || (a === 203 && b === 0 && c === 113)
        || a >= 224;
}

export function isPrivateOrReservedIpv6Literal(hostname: string): boolean {
    const host = hostname.toLowerCase().replace(/^\[|\]$/g, '').replace(/\.$/, '');
    if (!host.includes(':')) return false;

    // Zone identifiers select a local interface. IPv4-mapped/compatible forms
    // begin with :: and are deliberately rejected so alternate textual forms
    // cannot bypass the IPv4 checks above.
    if (host.includes('%') || host === '::' || host.startsWith('::')) return true;
    if (host.startsWith('fc') || host.startsWith('fd')) return true; // fc00::/7 ULA
    if (/^fe[89ab][0-9a-f]*:/i.test(host)) return true; // fe80::/10 link-local
    if (/^fe[c-f][0-9a-f]*:/i.test(host)) return true; // deprecated site-local
    if (host.startsWith('ff')) return true; // multicast
    if (host === '100::' || host.startsWith('100::')) return true; // discard-only 100::/64
    if (host === '2001:db8::' || host.startsWith('2001:db8:')) return true; // documentation
    return false;
}

function isLocalHostname(hostname: string): boolean {
    const host = hostname.toLowerCase().replace(/^\[|\]$/g, '').replace(/\.$/, '');
    if (!host) return true;
    if (host === 'localhost' || host.endsWith('.localhost')) return true;
    if (host.endsWith('.local') || host.endsWith('.internal') || host.endsWith('.lan')) return true;
    if (host === 'home' || host.endsWith('.home') || host === 'home.arpa' || host.endsWith('.home.arpa')) return true;

    // Single-label non-IP hostnames can be expanded through the machine's DNS
    // search suffix into a LAN target. Public web destinations should use a
    // qualified hostname.
    if (!host.includes('.') && !host.includes(':') && !ipv4Octets(host)) return true;
    return false;
}

/**
 * Edge/Workers-compatible literal URL boundary. This intentionally does not
 * claim to prevent DNS rebinding: deployments must still restrict private/LAN
 * egress at the network layer when the runtime allows it.
 */
export function isSafePublicHttpUrl(url: URL): boolean {
    if (!['http:', 'https:'].includes(url.protocol)) return false;
    if (url.username || url.password) return false;

    const host = url.hostname.toLowerCase().replace(/^\[|\]$/g, '').replace(/\.$/, '');
    if (isLocalHostname(host)) return false;
    if (isPrivateOrReservedIpv4Literal(host)) return false;
    if (isPrivateOrReservedIpv6Literal(host)) return false;
    return true;
}
