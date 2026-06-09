#!/usr/bin/env bash
# Install system libraries Playwright's Chromium needs on Debian/Raspberry Pi OS.
# Run once: sudo ./scripts/install-playwright-deps.sh
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Re-run with sudo: sudo $0" >&2
  exit 1
fi

PACKAGES=(
  libgbm1
  libatk1.0-0t64
  libatk-bridge2.0-0t64
  libatspi2.0-0t64
  libxkbcommon0
  libcairo2
  libpango-1.0-0
  libxcomposite1
  libxdamage1
  libxfixes3
  libxrandr2
  libnss3
  libnspr4
  fonts-liberation
)

echo "Installing Playwright browser dependencies..."
apt-get update
apt-get install -y "${PACKAGES[@]}"
echo "Done. Run: cd frontend && ./run run test:e2e"