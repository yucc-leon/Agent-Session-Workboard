"""Core layer: tmux control, session discovery, transcript parsing.

The fundamental unit is a *tmux pane running an agent CLI*. Everything the
control hub does is built on three robust primitives:

  - ``list-panes``    discover sessions (local or over SSH)
  - ``send-keys``     drive a session (inject a message / keystrokes)
  - ``capture-pane``  read a session's current screen

Remote machines are reached purely over SSH — no resident daemon required.
"""
