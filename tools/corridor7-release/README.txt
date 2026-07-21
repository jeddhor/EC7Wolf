Corridor 7: Alien Invasion — EC7Wolf
====================================

Run the game from a terminal with:

    ./run-corridor7.sh

The launcher keeps the configuration file and saved games in this directory.
Any additional EC7Wolf command-line options may be placed after the launcher
name. For example:

    ./run-corridor7.sh --nowait --tedlevel MAP01 --skill 2

The original Corridor 7 files in this directory came from the locally owned
Steam/CD installation used to build this package. Do not redistribute them.

This Linux executable is built on Ubuntu 20.04 for broad glibc compatibility,
with the C++ runtime statically linked. It uses the normal system libraries
(SDL2, audio, and graphics libraries) present on any modern desktop Linux
distribution. It is otherwise complete and needs no files from the source tree
or build directory.
