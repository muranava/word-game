from consts import SLACK_TOKEN, CHANNEL, SELF, USERNAME, GAME

from slackclient import SlackClient
import json
import random
import re
import csv
import datetime
import time

class Card(object):
    def __init__(self, word, kind, definition, example):
        self.word = word
        self.kind = kind
        self.definition = definition
        self.example = example

    def color(self):
        return {
            "root": "#0F13DB",
            "prefix": "good",
            "suffix": "danger",
        }[self.kind]

    def as_attachment(self):
        return {
            "title": self.word,
            "text": "%s; \"%s\"; Example: _%s_" % (self.kind, self.definition, self.example),
            "color": self.color(),
            "mrkdwn_in": ["text"],
        }


ROOT_WORDS = []
PREFIX_WORDS = []
SUFFIX_WORDS = []

with open('words.csv', 'rb') as f:
    reader = csv.reader(f, delimiter='|')
    for (kind, word, definition, example) in reader:
        card = Card(word, kind, definition, example)
        if kind == "root":
            ROOT_WORDS.append(card)
        elif kind == "prefix":
            PREFIX_WORDS.append(card)
        elif kind == "suffix":
            SUFFIX_WORDS.append(card)
        else:
            raise ValueError("Bad word kind: %s" % kind)

WAITING_FOR_START, WAITING_FOR_PLAYERS, WAITING_FOR_WORDS = range(3)

class Game(object):
    def __init__(self, sc):
        self.sc = sc
        self.state = WAITING_FOR_START

    def send(self, text, channel=CHANNEL, attachments=None):
        return json.loads(self.sc.api_call(
            "chat.postMessage",
            channel=channel,
            username=USERNAME,
            text=text,
            attachments=json.dumps(attachments)))['ts']

    def reply(self, message, text, attachments=None):
        self.sc.api_call(
            "chat.postMessage",
            channel=message['channel'],
            username=USERNAME,
            text=text,
            attachments=json.dumps(attachments))

    def react_with(self, emoji, ts, channel=CHANNEL):
        self.sc.api_call(
            "reactions.add",
            name=emoji,
            timestamp=ts,
            channel=channel)

    def handle_message(self, message):
        if re.search(r'\brules\b', message['text'].lower()):
            self.send("""How to play:
1. In each round, everyone will be given word parts, and there will be a main word part
2. Each person must combine their word parts to make a new, fake word, and come up with a (hopefully fun) definition of that word
3. At the end, everyone's words will be shown!
Have fun!""")
        elif message['text'] == 'reset':
            self.send("Resetting!")
            self.state = WAITING_FOR_START
            return

        elif self.state == WAITING_FOR_START:
            if re.search(r'\bnew\b', message['text'].lower()):
                self.players = set(["USLACKBOT"])
                self.new_game_message_ts = self.send("Starting a new game! React with :hand: to this message to join! Say _\"go\"_ to start the game.")
                self.react_with("hand", self.new_game_message_ts)
                self.state = WAITING_FOR_PLAYERS
            elif re.search(r'\bgo+\b', message['text'].lower()):
                self.send("A game hasn't been started! Say _\"new\"_ to start a new game.")

        elif self.state == WAITING_FOR_PLAYERS:
            if re.search(r'\bnew\b', message['text'].lower()):
                self.send("A game is already started! React with :hand: to the message above to join!")
            elif re.search(r'\bgo+\b', message['text'].lower()):
                if len(self.players) == 0:
                    self.send("Nobody has joined the current game yet :cry: React with :hand: to the message above to join!")
                    return

                self.state = WAITING_FOR_WORDS
                self.done_players = set()
                self.submissions = {}
                self.user_to_im = {}
                for user in self.players:
                    self.user_to_im[user] = self.get_im_for_user(user)

                self.deal_cards()

                self.start_game_message_ts = self.send(
                    """
Starting a new game of %s with %s!
React with :ok_hand: to this message when you are done. (You have been IMed your word parts individually)
The main word part is:""".strip() % (GAME, format_list(["<@%s>" % u for u in self.players])),
                     attachments=[self.main_word.as_attachment()])
                self.react_with("ok_hand", self.start_game_message_ts)

                for user, im in self.user_to_im.iteritems():
                    self.send("The main word part is:", channel=im,
                         attachments=[self.main_word.as_attachment()])
                    self.send("Your word parts are:", channel=im,
                         attachments=[card.as_attachment() for card in self.user_words[user]])
                    self.send(wantedform, channel=im)

        elif self.state == WAITING_FOR_WORDS:
            if re.search(r'\bnew\b', message['text'].lower()):
                self.send("A game is already in progress!")
            elif re.search(r'\bgo+\b', message['text'].lower()):
                self.send("A game is already in progress!")

    def handle_im(self, message):
        if self.state == WAITING_FOR_START:
            self.reply(message, "No game is running! Say _\"go\"_ in <#%s> to start a new game." % CHANNEL)
        elif self.state == WAITING_FOR_PLAYERS:
            self.reply(message, "A game is about to start! Visit <#%s> to join the game." % CHANNEL)
        elif self.state == WAITING_FOR_WORDS:
            user = message['user']
            if user not in self.players:
                self.reply(message, "You're not in the current game! Watch in <#%s> for new games starting." % CHANNEL)
                return

            text = message['text']
            match = reg.match(text)

            if not match:
                self.reply(message, wantedform)
            else:
                [word, parts, definition] = match.groups()

                cards = self.user_words[user] + [self.main_word]
                used_cards = sorted([
                    card for card in cards
                    if card.word in parts
                ], key=lambda x: parts.index(x.word))

                if not used_cards:
                    self.reply(message, "I couldn't find your cards in your word parts. %s" % wantedform)
                elif not self.main_word in used_cards:
                    self.reply(message, "I couldn't find the main word in your word parts. %s" % wantedform)
                else:
                    self.reply(message, "Your submission: *%s*: \"%s\"" % (word, definition), attachments=[c.as_attachment() for c in used_cards])
                    self.submissions[user] = (word, used_cards, definition)

    def handle_emoji_reaction(self, message):
        added = message['type'] == 'reaction_added'
        user = message['user']
        ts = message['item']['ts']
        reaction = message['reaction']

        if self.state == WAITING_FOR_PLAYERS and ts == self.new_game_message_ts and reaction == "hand":
            if added:
                self.players.add(user)
            else:
                self.players.remove(user)
        elif self.state == WAITING_FOR_WORDS and ts == self.start_game_message_ts and reaction == "ok_hand":
            if added:
                self.done_players.add(user)
            else:
                #!!
                self.done_players.remove(user)

            print self.done_players

            if self.check_for_done():
                self.send_words()

    def deal_cards(self):
        roots = list(ROOT_WORDS)
        prefixes = list(PREFIX_WORDS)
        suffixes = list(SUFFIX_WORDS)

        random.shuffle(roots)
        random.shuffle(prefixes)
        random.shuffle(suffixes)

        self.main_word = roots.pop()

        self.user_words = {}
        for user in self.players:
            self.user_words[user] = [
                prefixes.pop(),
                roots.pop(),
                roots.pop(),
                suffixes.pop(),
                suffixes.pop(),
            ]

    def check_for_done(self):
        if len(self.done_players) < len(self.players):
            return False

        return True

    def send_words(self):
        if len(self.submissions) == 0:
            self.send("Everyone readied up but nobody submitted words!? :confused: Game over, I guess?")
            self.state = WAITING_FOR_START
            return

        for user, (word, cards, definition) in self.submissions.iteritems():
            self.send("<@%s> made the word: *%s*, meaning: \"%s\", out of:" % (user, word, definition),
                 attachments=[card.as_attachment() for card in cards])
        self.state = WAITING_FOR_START

    def get_im_for_user(self, user):
        return json.loads(self.sc.api_call("im.open", user=user))['channel']['id']

def in_game_channel(message):
    return (
        message["type"] == "message" and
        message["channel"] == CHANNEL and
        "text" in message and
        "user" in message)

def in_private_chat(message, sc):
    ims = [im['id'] for im in json.loads(sc.api_call("im.list"))['ims']]

    return (
        message["type"] == "message" and
        message["channel"] in ims and
        "text" in message and
        "user" in message)

def is_emoji_reaction(message):
    return (
        (message['type'] == 'reaction_added' or message['type'] == 'reaction_removed') and
        message["item"]["type"] == "message" and
        message["item"]["channel"] == CHANNEL and
        message["user"] != SELF
    )

wantedform = "Reply in the form: \"word (word-o-parts): definition\". (E.g. \"superchronescence (super-chron-escence): the act of becoming a time-powered superhero\")"
reg = re.compile(r'\s*(\S+)\s*\("?([^)]+)"?\)\s*:\s*(.*)')

def format_list(things):
    if len(things) == 0:
        return ""
    elif len(things) == 1:
        return things[0]
    elif len(things) == 2:
        return "%s and %s" % (things[0], things[1])
    else:
        return "%s, and %s" % (', '.join(things[:-1]), things[-1])

def main():
    sc = SlackClient(SLACK_TOKEN)
    game = Game(sc)

    if sc.rtm_connect():
        while True:
            messages = sc.rtm_read()
            for message in messages:
                if in_game_channel(message):
                    game.handle_message(message)
                elif in_private_chat(message, sc):
                    game.handle_im(message)
                elif is_emoji_reaction(message):
                    game.handle_emoji_reaction(message)
            time.sleep(0.5)
    else:
        print "Connection Failed, invalid token?"


if __name__ == "__main__":
    main()
