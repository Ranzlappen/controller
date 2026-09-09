# Troubleshooting

Roughly in the order things go wrong. Every step here is something you can check yourself before filing an issue — and if you do file one, the output of these commands is what makes it fixable.

## `padmap devices` finds nothing

The controller is not reaching SDL at all. padmap is not involved yet.

- **Wired**: try a different USB port and cable. Xbox pads need a data cable; some charge-only cables look identical.
- **Bluetooth**: confirm the pad is actually *paired and connected*, not just paired. The Xbox button stays lit when connected.
- **Linux**: the `xpad` kernel driver handles Xbox pads. Check it loaded with `lsmod | grep xpad`, and that a device node exists at `/dev/input/js0` or `/dev/input/event*`. If the node exists but your user cannot read it, you are missing the `input` group: `sudo usermod -aG input $USER`, then log out and back in.
- **Windows**: check the pad appears under Settings → Bluetooth & devices. If Windows sees it and padmap does not, it is usually a stale `pygame` install — `pip install --upgrade pygame`.

## `padmap devices` finds it, but nothing happens when I run

Input is being generated but the OS is refusing to deliver it. This is the single most common problem, and it is a permission issue every time.

| Platform | Cause | Fix |
| --- | --- | --- |
| **macOS** | The terminal lacks Accessibility permission | System Settings → Privacy & Security → Accessibility → add and enable your terminal app. Restart the terminal afterwards; the permission is read at launch. |
| **Linux (Wayland)** | Wayland compositors reject synthetic input from ordinary processes | Log into an X11/Xorg session at the login screen. There is no workaround from inside padmap. |
| **Linux (X11)** | Usually nothing — this combination works | If it doesn't, check `echo $DISPLAY` is set. |
| **Windows** | An elevated window is in focus | A non-elevated process cannot send input to an elevated one. Run padmap as administrator *only* if you need it for a specific elevated app. |
| **Games** | Anti-cheat blocks synthetic input by design | padmap cannot work around this and will not gain features that try. |

Confirm padmap's own side is fine first:

```
padmap run --dry-run
```

If the dry run prints events as you press buttons, padmap's mapping is working and the problem is entirely on the delivery side — go back to the table above.

## The wrong button does the wrong thing

Drivers disagree about which raw index is which physical button. Find out what yours actually reports:

```
padmap monitor
```

Press each button and note the index it prints. Then pin the ones that are wrong in your profile:

```json
"device": {
  "layout": { "a": 0, "b": 1, "x": 2, "y": 3 }
}
```

`padmap validate <your-profile.json>` confirms the file still parses.

## The triggers are half-pressed at rest, or only work in the top half

Most drivers report the triggers as `-1` (released) to `1` (pulled); a few use `0` to `1`. padmap samples them at startup to decide which, but the guess can go wrong if a trigger is held while padmap starts. Pin it:

```json
"device": { "trigger_mode": "signed" }
```

Use `"unipolar"` for the other convention, or `"auto"` (the default) to go back to detection. `padmap monitor` shows the resting value: `-1.00` means signed, `0.00` means unipolar.

## The pointer drifts when I'm not touching the stick

Worn sticks rest slightly off-centre. Raise the deadzone until it stops:

```json
"sticks": { "left": { "mode": "mouse", "deadzone": 0.25 } }
```

`padmap monitor` shows the resting axis values — a stick reading `0.08` at rest needs a deadzone above `0.08`.

## The pointer is too fast, too slow, or too twitchy

Three separate dials, and they do different things:

- **`speed`** — pixels per second at full deflection. Raise it to cover more screen.
- **`curve`** — how the middle of the range behaves. `1.0` is linear; `2.0` (the default) gives a slow, precise centre and a fast outer range; below `1.0` is twitchier near centre. If fine positioning is hard but big movements are fine, raise the curve rather than lowering the speed.
- **`deadzone`** — how far you must push before anything happens.

Raising `poll_hz` (up to 200 or so) makes motion smoother, not faster.

## A key is stuck down

Press the pause button on the pad (**Back / View** in every bundled profile), or `Ctrl-C` in the terminal — both release everything. If a modifier is genuinely still held afterwards, tap it on your physical keyboard to clear the OS's idea of its state.

Then please report it through [private vulnerability reporting](https://github.com/Ranzlappen/controller/security/advisories/new) rather than a public issue: a stuck modifier reinterprets every subsequent keystroke, which makes it the most serious class of bug padmap can have. Include the profile and what you were doing.

## A profile won't load

`padmap validate <file>` prints the exact path of the problem — `sticks.left.curve: 9.0 is out of range [0.1, 6.0]`. padmap rejects unknown keys on purpose: a typo that got silently ignored would look exactly like broken hardware.

Common ones:

- A trailing comma, or a comment. Profiles are strict JSON; `//` comments are not allowed.
- `turbo` and `toggle` on the same binding — deliberately rejected, since a latched auto-fire is a footgun.
- A key name padmap doesn't know. The error lists every valid name.

## Still stuck

Open a [bug report](https://github.com/Ranzlappen/controller/issues/new/choose) with your profile, the output of `padmap devices`, and your platform. The issue template asks for exactly those.
