#!/bin/sh
# Render's dockerCommand field takes a single string it parses itself before
# exec'ing it — two different quoting styles for an inline
# `sh -c "alembic ... && uvicorn ..."` both failed on a real Render deploy
# (exit 127, the whole "alembic ... && uvicorn ..." string looked up as one
# literal command name instead of being shell-parsed). Whatever Render's
# exact parsing rule is, a single space-free executable path removes the
# ambiguity entirely: nothing left for it to mis-split.
set -e

alembic upgrade head
exec uvicorn doda.main:app --host 0.0.0.0 --port "$PORT"
