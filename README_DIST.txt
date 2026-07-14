================================================================
 Ultra Fast Zip v1.0
 High-speed archive tool for massive file trees
 Designed by Codecider Lab
================================================================

[Contents]

  UltraFastZip\UltraFastZip.exe       GUI application (keep the folder intact)
  ufz.exe                             CLI tool (single file)
  UltraFastZip_UserManual.pdf         user manual
  README.txt                          this file

[Quick start - GUI]

  1. Run UltraFastZip.exe inside the UltraFastZip folder
  2. Compress tab: pick a folder -> Start Compression
  3. Extract tab: pick an archive -> Start Extraction
     (.ufz plus zip/7z/rar/tar/gz/cab/iso are auto-detected)

  * UltraFastZip.exe does not run if copied out alone.
    Copy the whole folder.

[Quick start - CLI]

  ufz pack <folder>            compress a folder into .ufz
  ufz unpack <archive>         extract (format auto-detected)
  ufz inspect <file.ufz>       show archive info
  ufz <command> -h             per-command help

  ufz.exe is standalone; copy it anywhere you like
  (add it to PATH to use ufz from any prompt).

  Legacy .fpk archives extract as-is.

[System requirements]

  Windows 10/11 64-bit
  No installer or runtime required

This program is MIT-licensed open source (see LICENSE).
