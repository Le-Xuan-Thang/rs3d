# RS3D Guide

Short version of the project Manual (`docs/Manual.odt`). The Status page tells you which section you need.

## 1. Connect

1. Put the Shake on a solid, level floor, away from doors, fans and footsteps.
2. Connect the Shake's Ethernet port directly to the laptop with a cable.
3. Power the Shake and wait 3–5 minutes.
4. Open **Status**. If **Laptop IP** is red, press **Set IP**.

The Shake gives itself a `169.254.x.x` address (ours: `169.254.221.62`, name `rs.local`).

## 2. Add the Shake to the app

- Use **Find Shake…** in the sidebar, or
- open **Settings**, enter the IP, the SSH user (`myshake`) and password, then **Test connection**.

The password is stored in your operating system's password store, never in a file.

## 3. Status checks

| Check | Meaning |
|---|---|
| Laptop IP | the laptop has a `169.254.x.x` address on the cable |
| SeedLink | live data port 18000 answers |
| Channels | EHZ, EHN, EHE are served |
| SSH | the app can log in to read clock, storage and archive |
| Clock | time offset and time source of the Shake |
| Internet / Wi-Fi | the Shake reaches the Internet (for its clock) |
| Storage | free space on the Shake's SD card |
| Archive | days stored on the Shake, retention (7 days) |
| Data Forwarding | public data sharing is off |
| Password | the default password was changed |

Hover a **(?)** for a hint, click it for the full explanation and fix.

## 4. Live

Three channels in real time. Choose the window (30 s, 60 s, 5 min), switch the 1–10 Hz filter on or off, pause, and use **Save this segment** to open the same range on the Data page.

## 5. Data

1. Choose **Start** and **End**, use **Presets**, or drag on the coverage bar.
2. **Download & preview** copies the needed day files from the Shake.
3. Choose channels, band-pass filter and units (counts or m/s).
4. Export as **miniSEED**, **CSV**, **PNG**, **PDF**, or get the **Code** (ObsPy) to reproduce it.

The Shake keeps only **7 days**: download at least once a week.

## 6. Clock

The Shake keeps time with `ntpd`, from Internet servers over Wi-Fi, with the laptop (`169.254.8.11`) as a backup. Check on the Shake:

```
ntpq -pn
```

A line starting with `*` is the selected source; `offset` is in milliseconds.

## Wi-Fi: two addresses

If `ip -4 addr show wlan0` on the Shake lists two addresses, Internet comes and goes. Two DHCP clients manage `wlan0`. Fix on the Shake:

```
sudo cp -p /etc/dhcpcd.conf /etc/dhcpcd.conf.bak-rs3d
sudo sed -i '/^denyinterfaces wlan0$/d' /etc/dhcpcd.conf
sudo sed -i '1i denyinterfaces wlan0' /etc/dhcpcd.conf
sudo reboot
```

Saving network settings in the Shake web page may bring the problem back.
