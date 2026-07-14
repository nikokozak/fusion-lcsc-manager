#!/bin/bash
set -euo pipefail

VERSION="${1:-0.1.0}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="fusion-lcsc-manager-${VERSION}"
STAGE="${ROOT}/release/${NAME}/LCSCManagerFusion"
ZIP="${ROOT}/release/${NAME}.zip"

if [[ ! "${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Version must use x.y.z format" >&2
  exit 1
fi

MANIFEST_VERSION="$(sed -n 's/.*"version": "\([^"]*\)".*/\1/p' "${ROOT}/fusion/LCSCManagerFusion/LCSCManagerFusion.manifest")"
if [[ "${VERSION}" != "${MANIFEST_VERSION}" ]]; then
  echo "Version ${VERSION} does not match add-in manifest ${MANIFEST_VERSION}" >&2
  exit 1
fi

rm -rf "${ROOT}/release/${NAME}" "${ZIP}"
mkdir -p "${STAGE}/lib"

cp -R "${ROOT}/fusion/LCSCManagerFusion/." "${STAGE}/"
cp -R "${ROOT}/plugins/lcsc_manager" "${STAGE}/lcsc_manager"

python3 -m pip install --quiet --upgrade --target "${STAGE}/lib" \
  requests certifi charset-normalizer idna urllib3

find "${STAGE}" -type d -name __pycache__ -prune -exec rm -rf {} +
find "${STAGE}" -type f \( -name '*.pyc' -o -name '.DS_Store' \) -delete
find "${STAGE}/lib" -type f \( -name '*.so' -o -name '*.pyd' \) -delete
find "${STAGE}/lib" -type d -name '*.dist-info' -prune -exec rm -rf {} +
rm -rf "${STAGE}/lib/bin"

mkdir -p "${ROOT}/release"
(
  cd "${ROOT}/release/${NAME}"
  zip -qr "${ZIP}" LCSCManagerFusion
)

echo "Built ${ZIP}"
