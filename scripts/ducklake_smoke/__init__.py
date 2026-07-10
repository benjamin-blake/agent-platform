"""DuckLake Neon smoke-test gate package (T2.16b / T2.18 / CD.34 / rec-2414).

Package marker only. The public entry point stays scripts/ducklake_neon_smoke_test.py
(byte-stable CLI facade); import gate functions from that facade, not this package,
unless writing package-internal code (see the facade's re-export block for the full
surface).
"""
