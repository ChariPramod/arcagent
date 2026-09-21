// Set only by the Sites Vite build, never by a request header or runtime environment.
declare const __ARCAGENT_SITES_AUTH__: boolean;
export function hasTrustedSitesIdentity(): boolean {
  return (
    typeof __ARCAGENT_SITES_AUTH__ !== 'undefined' &&
    __ARCAGENT_SITES_AUTH__ === true
  );
}
