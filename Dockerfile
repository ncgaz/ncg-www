FROM pierrezemb/gostatic
COPY --chown=appuser:appuser ./site/ /srv/http/
ENTRYPOINT ["/goStatic", "-fallback", "/index.html"]
