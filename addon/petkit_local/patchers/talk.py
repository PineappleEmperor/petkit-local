"""Two-way talk (intercom) audio sink patcher.

PetKit's app talks to the litter box over Agora RTC; the camera patcher replaces
Agora with tserver (local video, one-way), which is why talkback stops working
once you leave the cloud. Listening still works — the device mic rides the
tserver FLV as 16 kHz AAC — so the only missing half is getting the panel's
microphone TO the device speaker.

This patcher adds that half without any new on-device binary. Its pre-init block
(`common.PRE_INIT_BLOCKS["talk"]`) runs a small `nc` listener on TCP
`TALK_TCP_PORT`. Per connection it feeds a named pipe to the firmware's own
`pktool play_aac`, which hands the path to `media`; media stream-reads the pipe
and plays it on the speaker. The add-on's `/api/devices/{id}/talk` WebSocket
transcodes the browser microphone to 16 kHz mono ADTS-AAC and streams it in.

It is a pre-init block rather than a bind-mount because it starts a process
rather than replacing a binary — the same shape as the SSH patcher. Starting it
before stock init is safe even though it ends up driving pktool: the listener
only needs to be LISTENING at boot, and the speaker path is touched lazily, per
connection, by which time stock init has long since started media.

Like camera, nothing of ours lands on persistent storage — the listener script
is regenerated in /tmp on every boot — so `files` is empty and removal is just
dropping the block from the wrapper and rebooting. Half-duplex by design: mute
listening while talking, because the device's native echo cancellation lived on
the Agora path this replaces.
"""
from __future__ import annotations

from petkit_local.patchers.common import TALK_TCP_PORT

PATCHER_INFO = {
    "id": "talk",
    "name": "Two-Way Talk (Intercom)",
    "description": (
        "Adds a local audio sink so the panel can talk to the device speaker — "
        "real two-way audio without PetKit's cloud, which used Agora (replaced "
        "by Local Camera Streaming).\n\n"
        f"What it does: adds a pre-init block to the boot wrapper that runs a "
        f"small nc listener on TCP {TALK_TCP_PORT}. Per connection it feeds a "
        "named pipe to the firmware's own pktool play_aac, which hands it to "
        "media (the IMP pipeline that owns the speaker). The add-on transcodes "
        "your browser microphone to 16 kHz mono AAC and streams it in; listening "
        "is the existing camera audio the other way.\n\n"
        "Requires a camera model with a speaker, and is normally used together "
        "with Local Camera Streaming. Nothing is written to persistent storage — "
        "the listener script is regenerated in /tmp each boot — so removing the "
        "patch and rebooting restores stock exactly.\n\n"
        "Half-duplex: mute listening while you talk to avoid echo (the device's "
        "native echo cancellation lived on the Agora path this replaces)."
    ),
    # Pure pre-init block: no file of ours lands on the device (nc + pktool are
    # stock, the sink script is generated in /tmp), so removal is just dropping
    # the block from the wrapper and rebooting (cf. camera).
    "files": [],
    # No architecture: the sink is stock busybox nc + pktool, both already there.
    "arch": None,
    # Writes no file of its own, but every patcher rewrites /system/app_init.sh —
    # so the floor is the wrapper plus margin, not zero (cf. camera).
    "needs_bytes": 131072,
}
