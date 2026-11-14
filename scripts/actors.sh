#!/usr/bin/env bash
# Test Kin alone: your Mac's built-in speakers play the other people (Kin itself talks in your earbuds).
# Hold the band ~30 cm from the laptop speakers.
#   bash scripts/actors.sh sarah      # your daughter visits
#   bash scripts/actors.sh leo        # your grandson with news
#   bash scripts/actors.sh scam       # a fake "grandson in jail" scam call
#   bash scripts/actors.sh doctor     # medication instructions
#   bash scripts/actors.sh neighbor   # a favour for Saturday
#   bash scripts/actors.sh cashier    # small talk Kin should ignore
# The Mac's built-in speakers by device NUMBER (macOS `say -a "<name>"` crashes on some names).
SPK="${KIN_ACTOR_SPEAKERS:-$(say -a '?' 2>/dev/null | grep -i 'speaker' | head -1 | awk '{print $1}')}"
line() {
  if [ -n "$SPK" ]; then say -a "$SPK" -v "$1" -r 165 "$2" || say -v "$1" -r 165 "$2"; else say -v "$1" -r 165 "$2"; fi
  sleep 0.6
}
case "${1:-}" in
  sarah)    line Samantha "Hi Dad, it's Sarah!"
            line Samantha "I just wanted to tell you, I'm moving to Oakland next week for my new job."
            line Samantha "I'll call you on Sunday to see how you're doing." ;;
  leo)      line Daniel "Hi Grandpa, it's Leo!"
            line Daniel "Guess what, I got into Berkeley! I start in the fall." ;;
  scam)     line Fred "Grandpa? It's me, your grandson. I'm in trouble."
            line Fred "I got arrested and I need two thousand dollars for bail, right now."
            line Fred "Please buy gift cards and read me the numbers. And don't tell Mom, okay?" ;;
  doctor)   line Karen "Hello Joe, this is Doctor Patel's office."
            line Karen "Please take your new blood pressure pill with food, twice a day, starting tomorrow." ;;
  neighbor) line Ralph "Hey Joe, it's Mike from next door."
            line Ralph "Could you water my plants on Saturday while I'm away?" ;;
  cashier)  line Tessa "Hi there, what can I get for you today?"
            line Tessa "That'll be four fifty. Have a nice day!" ;;
  *) sed -n '2,10p' "$0"; exit 1 ;;
esac
