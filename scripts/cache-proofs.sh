#!/bin/sh
# The cache model's kernel-checked property: every sequence of three accesses over
# CacheCheck.wiz's alphabet, for write-back/write-through and allocate/no-allocate
# (proofs/CacheProof.wiz). The four-access version is tests/cache.wiz's evaluation.
set -eu
cd "$(dirname "$0")/.."
exec wiz check -I src proofs/CacheProof.wiz
