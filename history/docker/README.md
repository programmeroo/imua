# Archived: docker-compose.yml

Retired 2026-11-08. Nothing runs Imua with Docker Compose.

The live hub on HUB-1 runs with plain `docker run`, built from the `Dockerfile` at the
repo root (still in use). Its config and data are bind-mounted from host folders. This
compose file stored data in a named volume (`imua_data`) instead. Running it on HUB-1
would start the hub against an empty database, so it was archived to prevent that.

For the current build and run commands, see the main `README.md` ("Start Imua").
