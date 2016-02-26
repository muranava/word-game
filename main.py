from consts import SLACK_TOKEN, CHANNEL, SELF, USERNAME

from slackclient import SlackClient
import time
import json
import random
import re

class Card(object):
    def __init__(self, word, kind):
        self.word = word
        self.kind = kind

    def color(self):
        return {
            "root": "#0F13DB",
            "prefix": "good",
            "suffix": "danger",
        }[self.kind]

    def as_attachment(self):
        return {
            "title": self.word,
            "text": "%s; boo" % self.kind,
            "color": self.color()
        }

    def __str__(self):
        return "word: %s" % self.word

class Game(object):
    ROOT_WORDS = [Card(x, "root") for x in ["cald", "cardi", "chron", "hack", "potat", "aqua"]]
    PREFIX_WORDS = [Card(x, "prefix") for x in ["super-", "a-", "penta-"]]
    SUFFIX_WORDS = [Card(x, "suffix") for x in ["-saurus", "-thon", "-ectomy", "-ible", "-escence"]]

    def __init__(self, users):
        roots = list(self.ROOT_WORDS)
        prefixes = list(self.PREFIX_WORDS)
        suffixes = list(self.SUFFIX_WORDS)

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

def main():
    sc = SlackClient(SLACK_TOKEN)
    user_to_im = {}
    game = None

    if sc.rtm_connect():
        while True:
            messages = sc.rtm_read()
            for message in messages:
                if in_game_channel(message):
                    if message['text'] == "go":
                        users = [u for u in json.loads(sc.api_call("channels.info", channel=CHANNEL))['channel']['members'] if u != SELF]
                        user_to_im = {}
                        for user in users:
                            user_to_im[user] = json.loads(sc.api_call("im.open", user=user))['channel']['id']

                        game = Game(user_to_im.keys())
                        sc.api_call(
                            "chat.postMessage",
                            channel=CHANNEL,
                            username=USERNAME,
                            text="The main word is: (You have been IMed your cards)",
                            attachments=json.dumps([game.main_word.as_attachment()]))
                        for user, im in user_to_im.iteritems():
                            sc.api_call(
                                "chat.postMessage",
                                channel=im,
                                username=USERNAME,
                                text="The main word is:",
                                attachments=json.dumps([game.main_word.as_attachment()]))
                            sc.api_call(
                                "chat.postMessage",
                                channel=im,
                                username=USERNAME,
                                text="Your words are:",
                                attachments=json.dumps([card.as_attachment() for card in game.user_words[user]]))
                    elif message['text'] == "done":
                        if game:
                            if len(game.submissions) == len(user_to_im):
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
                                    text="Not everybody has submitted a word!")

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
                    elif user not in user_to_im:
                        reply("You're not in the current game. Join <#%s> to be part of games." % CHANNEL)
                    else:
                        text = message['text']

                        reg = re.compile(r'\s*(\S+)\s*\("?([^)]+)"?\)\s*:\s*(.*)')
                        wantedform = "Reply in the form: \"word (word-o-parts): definition\". (E.g. \"superchronescence (super-chron-escence): the act of becoming a time-powered superhero\")"
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
