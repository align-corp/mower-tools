## Mac
1. use Icon Composer to create and export cute icons
2. create a folder `MyIcon.iconset` with exact these files:
```
MyIcon.iconset/
├── icon_16x16.png       (16x16)
├── icon_16x16@2x.png    (32x32)
├── icon_32x32.png       (32x32)
├── icon_32x32@2x.png    (64x64)
├── icon_128x128.png     (128x128)
├── icon_128x128@2x.png  (256x256)
├── icon_256x256.png     (256x256)
├── icon_256x256@2x.png  (512x512)
├── icon_512x512.png     (512x512)
└── icon_512x512@2x.png  (1024x1024)
```
3. Convert to .icns
```
iconutil -c icns MyIcon.iconset -o icon.icns
```

## Windows
1. go to https://www.icoconverter.com/
2. generate icon.ico

## Pyinstaller
add option `--icon=icon.icns` for Mac,
`--icon=icon.ico` for Windows,
`--icon=icon.png` for Linux
