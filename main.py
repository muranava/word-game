from consts import SLACK_TOKEN, CHANNEL, SELF, USERNAME, GAME

from slackclient import SlackClient
import json
import random
import re
import csv
import datetime

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

class Game(object):

    def __init__(self, users):
        roots = list(ROOT_WORDS)
        prefixes = list(PREFIX_WORDS)
        suffixes = list(SUFFIX_WORDS)

        random.shuffle(roots)
        random.shuffle(prefixes)
        random.shuffle(suffixes)

        self.main_word = roots.pop()

        self.user_words = {}
        for user in users:
            self.user_words[user] = [
                prefixes.pop(),
                roots.pop(),
                roots.pop(),
                suffixes.pop(),
                suffixes.pop(),
            ]

        self.submissions = {}
        self.starttime = datetime.datetime.now()

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
    user_to_im = {}
    game = None
    players = set()
    starting_game = False

    def send(channel, text, attachments=None):
        sc.api_call(
            "chat.postMessage",
            channel=channel,
            username=USERNAME,
            text=text,
            attachments=json.dumps(attachments))

    if sc.rtm_connect():
        while True:
            messages = sc.rtm_read()
            for message in messages:
                if in_game_channel(message):
                    if re.search(r'\bnew\b', message['text'].lower()):
                        if game:
                            sc.api_call(
                                "chat.postMessage",
                                channel=CHANNEL,
                                username=USERNAME,
                                text="A game is already in progress! Say 'done' to show results of the current game.")
                            continue
                        elif starting_game:
                            sc.api_call(
                                "chat.postMessage",
                                channel=CHANNEL,
                                username=USERNAME,
                                text="A game is already started! Say 'join' to join.")
                            continue

                        players = set()
                        starting_game = True
                        send(CHANNEL, "Starting a new game! Say 'join' to join in!")
                    elif re.search(r'\bjoin\b', message['text'].lower()):
                        if game:
                            sc.api_call(
                                "chat.postMessage",
                                channel=CHANNEL,
                                username=USERNAME,
                                text="A game is already in progress!")
                            continue
                        elif not starting_game:
                            sc.api_call(
                                "chat.postMessage",
                                channel=CHANNEL,
                                username=USERNAME,
                                text="A game hasn't been started! Say 'new' to start a new game.")
                            continue

                        players.add(message['user'])
                    elif re.search(r'\bgo+\b', message['text'].lower()):
                        if not starting_game:
                            send(CHANNEL, "A game hasn't been started! Say 'new' to start a new game.")
                            continue
                        elif starting_game and len(players) == 0:
                            send(CHANNEL, "Nobody has joined the current game yet :(. Say 'join' to join the game!")
                            continue
                        elif game:
                            sc.api_call(
                                "chat.postMessage",
                                channel=CHANNEL,
                                username=USERNAME,
                                text="A game is already in progress! Say 'done' to show results of the current game.")
                            continue

                        starting_game = False
                        user_to_im = {}
                        for user in players:
                            user_to_im[user] = json.loads(sc.api_call("im.open", user=user))['channel']['id']

                        game = Game(user_to_im.keys())
                        sc.api_call(
                            "chat.postMessage",
                            channel=CHANNEL,
                            username=USERNAME,
                            text="Starting a new game of %s with %s!\nSay 'done' when everyone is done! (You have been IMed your word parts individually)\nThe main word part is:" % (GAME, format_list(["<@%s>" % u for u in players])),
                            attachments=json.dumps([game.main_word.as_attachment()]))
                        for user, im in user_to_im.iteritems():
                            sc.api_call(
                                "chat.postMessage",
                                channel=im,
                                username=USERNAME,
                                text="The main word part is:",
                                attachments=json.dumps([game.main_word.as_attachment()]))
                            sc.api_call(
                                "chat.postMessage",
                                channel=im,
                                username=USERNAME,
                                text="Your word parts are:",
                                attachments=json.dumps([card.as_attachment() for card in game.user_words[user]]))
                            sc.api_call(
                                "chat.postMessage",
                                channel=im,
                                username=USERNAME,
                                text=wantedform)
                    elif re.search(r'\bdone\b', message['text'].lower()):
                        if game:
                            if len(game.submissions) == len(user_to_im) or ((datetime.datetime.now() - game.starttime).seconds > 180 and len(game.submissions) > 0):
                                for user, (word, cards, definition) in game.submissions.iteritems():
                                    sc.api_call(
                                        "chat.postMessage",
                                        channel=CHANNEL,
                                        username=USERNAME,
                                        text=("<@%s> made the word: *%s*, meaning: \"%s\", out of:" % (user, word, definition)),
                                        attachments=json.dumps([card.as_attachment() for card in cards]))
                                game = None
                            else:
                                sc.api_call(
                                    "chat.postMessage",
                                    username=USERNAME,
                                    channel=CHANNEL,
                                    text="Not everybody has submitted a word! (%s)" % " ".join(["<@%s>" % u for u in list(set(user_to_im.keys()) - set(game.submissions.keys()))]))
                                continue
                        else:
                            send(CHANNEL, "No game running right now! Say 'new' to start a new game.")
                    elif re.search(r'\brules\b', message['text'].lower()):
                        send(CHANNEL, """How to play:
1. In each round, everyone will be given word parts, and there will be a main word part
2. Each person must combine their word parts to make a single word, and define that word
3. At the end, everyone's words will be shown!
Have fun!""")
                    elif message['text'] == 'reset':
                        send(CHANNEL, "Resetting!")
                        game = None
                        starting_game = False
                        players = set()

                elif in_private_chat(message, sc):
                    user = message['user']

                    def reply(m, att=None):
                        sc.api_call(
                            "chat.postMessage",
                            channel=message['channel'],
                            username=USERNAME,
                            text=m,
                            attachments=json.dumps(att))

                    if not game:
                        reply("No game is running! Say \'go\' in <#%s> to start a new game." % CHANNEL)
                        continue
                    elif user not in user_to_im:
                        reply("You're not in the current game. Join <#%s> to be part of games." % CHANNEL)
                        continue

                    text = message['text']

                    match = reg.match(text)

                    if not match:
                        reply(wantedform)
                    else:
                        [word, parts, definition] = match.groups()

                        cards = game.user_words[user] + [game.main_word]
                        used_cards = sorted([
                            card for card in cards
                            if card.word in parts
                        ], key=lambda x: parts.index(x.word))

                        if not used_cards:
                            reply("I couldn't find your cards in your word parts. %s" % wantedform)
                        elif not game.main_word in used_cards:
                            reply("I couldn't find the main word in your word parts. %s" % wantedform)
                        else:
                            reply("Your submission: *%s*: \"%s\"" % (word, definition), att=[c.as_attachment() for c in used_cards])
                            game.submissions[user] = (word, used_cards, definition)

    else:
        print "Connection Failed, invalid token?"


if __name__ == "__main__":
    main()
