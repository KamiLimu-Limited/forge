# Development shell for NixOS: `nix-shell` (or `nix-shell --command fish`).
#
# Prebuilt pip wheels (greenlet, asyncpg, argon2-cffi, ...) expect the usual
# Linux system libraries, which NixOS doesn't provide globally. This shell
# exposes them via LD_LIBRARY_PATH and activates the project's uv venv.
{ pkgs ? import <nixpkgs> { } }:

pkgs.mkShell {
  packages = with pkgs; [
    python313
    uv
    ruff
    postgresql
  ];

  LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [
    pkgs.stdenv.cc.cc.lib
    pkgs.zlib
  ];

  # Use the Nix-provided interpreter instead of uv-downloaded ones (those can't run on NixOS).
  UV_PYTHON = "${pkgs.python313}/bin/python3";
  UV_PYTHON_DOWNLOADS = "never";

  shellHook = ''
    if [ ! -d .venv ]; then
      uv venv .venv
      uv pip install -e '.[dev]'
    fi
    export VIRTUAL_ENV="$PWD/.venv"
    # Nix's ruff first: the wheel's binary in the venv is dynamically linked for generic Linux.
    export PATH="${pkgs.ruff}/bin:$VIRTUAL_ENV/bin:$PATH"
  '';
}
