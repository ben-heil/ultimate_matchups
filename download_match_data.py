# Analyze char vs character matchups
# Analyze which stages are good for a character in general
# If there's enough data, analyze stages for a character against other chars
import datetime
import json
import sys

from graphqlclient import GraphQLClient
import pandas as pd
import ratelimiter
import urllib

# TODO this should be a config file
TOKEN_FILE = 'token.txt'
ID_TO_CHAR_FILE = 'character_to_id.csv'
OUT_FILE = 'game_data.csv'
API_URL = 'https://api.smash.gg/gql/'
API_VERSION = 'alpha'
ULTIMATE_ID = 1386 # This is smash.gg's internal representation of smash ultimate


def add_months(sourcedate, months):
    """https://stackoverflow.com/questions/4130922/how-to-increment-datetime-by-custom-months-in-python-without-using-library"""
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    return datetime.datetime(year, month, 1)


def parse_id_to_char_file(in_file):
    """ Get the id to character mapping from the manually curated id to character file """
    id_to_char = {}
    with open(in_file) as id_to_char_file:
        for line in id_to_char_file:
            if len(line.strip()) == 0:
                continue
            char, id_ = line.strip().split(',')
            id_to_char[int(id_)] = char
    return id_to_char


@ratelimiter.RateLimiter(max_calls=60, period=60)
def call_api(query, params, client):
    """ A wrapper for api calls so we can respect the rate limit """
    not_done = True
    while not_done:
        try:
            result = json.loads(client.execute(query, params))
            return result
        except urllib.error.HTTPError:
            print('520 error')
            pass


def event_is_ultimate(event: dict) -> bool:
    """ Determine whether an event object returned from smashgg's API is
    an event where the players are playing Smash Ultimate

    Arguments
    ---------
    event: The json returned from the graphQL query containing information about the event

    Returns
    -------
    is_ultimate: Whether the event is a Smash Ultimate event
    """
    try:
        game_id = event['videogame']['id']
        return game_id == ULTIMATE_ID
    except KeyError:
        return False

def update_start(tournaments):
    """Update the start date for the tournaments query based on the most recent data"""
    # This is fragile, but should only have to work like twice
    return tournaments[0]['events'][0]['createdAt']


def get_ultimate_events(client):
    """ Query the smash.gg api to get all the events where people played smash ultimate singles """
    event_ids = set()
    query = '''query TournamentsByVideogame($perPage: Int!, $page: Int!, $video_game: ID! $after: Timestamp!, $before: Timestamp!) {
                tournaments(query: {
                    perPage: $perPage
                    page: $page
                    filter: {
                      afterDate: $after
                      beforeDate: $before
                      past: true
                      videogameIds: [$video_game]
                    }
                }) {
                    nodes {
                      id
                      name
                      events(limit: 100) {
                        id
                        name
                        createdAt
                        isOnline
                        state
                        videogame{
                          id
                        }
                      }
                    }
                }
                },
            '''


    done_iterating = False
    today = datetime.datetime.now()
    start_date = datetime.datetime(2018, 12, 1)
    next_date = add_months(start_date, 1)

    while start_date < today:
        print(start_date, next_date)
        i = 1

        start_stamp = int(start_date.timestamp())
        next_stamp = int(next_date.timestamp())

        while True:
            parameters = {'page': i, 'perPage': 30, 'video_game': ULTIMATE_ID,  'after': start_stamp, 'before': next_stamp}

            result = call_api(query, parameters, client)

            tournaments = result['data']['tournaments']['nodes']
            # Totalpages doesn't work for stopping because it caps at 999 without mentioning it
            if tournaments is None:
                break

            print(i)

            for tournament in tournaments:
                events = tournament['events']
                if events is None:
                    continue
                for event in events:
                    # Keep only smash ultimate online matches from completed events
                    date = datetime.datetime.fromtimestamp(event['createdAt'])
                    if not event_is_ultimate(event):
                        continue
                    if not event['isOnline']:
                        continue
                    if not event['state'] == 'COMPLETED':
                        continue
                    event_ids.add(event['id'])
            i += 1

        start_date = next_date
        next_date = add_months(next_date, 1)

    return event_ids


def set_is_singles(slots):
    """Check whether a set is in the singles or doubles format based on its slots"""
    if slots is None:
        return False
    for slot in slots:
        entrant = slot['entrant']
        try:
            participants = entrant['participants']
            if len(participants) > 1:
                return False
            else:
                return True
        except KeyError:
            return True


def get_participant_ids(slots):
    """Get the participant ids for a the set's slots
    there should be two for singles and four for doubles"""
    participant_ids = []
    for slot in slots:
        entrant = slot['entrant']
        participant_ids.append(entrant['id'])

    return participant_ids


def parse_selection(selection, id_to_char):
    """ Find the entrant name, character name, and entrant id associated with a
    character selection
    """
    if selection['entrant'] is None:
        return None, None, None
    entrant_id = selection['entrant']['id']
    entrant_name = selection['entrant']['name']

    character_id = selection['selectionValue']
    character_name = None
    if character_id in id_to_char:
        character_name = id_to_char[character_id]
    else:
        sys.stderr.write('Character with id {} is not in the file\n'.format(character_id))

    return entrant_id, character_name, entrant_name


def update_game_data(games: dict, id_to_char: dict, game_data: dict) -> dict:
    """ Parse a set and use the information to update the game_data object """
    for game in games:
        game_selections = game['selections']
        if game_selections is None:
            continue
        winner = game['winnerId']

        stage = None
        if game['stage'] is not None:
            stage = game['stage']['name']

        first_selection = True
        entrant1 = None
        char1 = None
        entrant2 = None
        char2 = None
        entrant1_name = None
        entrant2_name = None
        for selection in game_selections:
            if selection['selectionType'] != 'CHARACTER':
                continue
            if first_selection:
                entrant1, char1, entrant1_name = parse_selection(game_selections[0], id_to_char)
                first_selection = False
            else:
                entrant2, char2, entrant2_name = parse_selection(game_selections[1], id_to_char)

        if entrant1 == winner or entrant2 == winner:
            game_data['char1'].append(char1)
            game_data['char2'].append(char2)
            game_data['winner'].append(char2)
            game_data['stage'].append(stage)
            game_data['entrant1'].append(entrant1_name)
            game_data['entrant2'].append(entrant2_name)
        else:
            if char1 is not None and char2 is not None:
                sys.stderr.write('Data from only one player\n')


    return game_data


def get_sets_for_events(event_ids: list) -> dict:
    """ Query each event and download its associated data

    Arguments
    ---------
    event_ids: the identifiers allowing us to select each smash ultimate event

    Returns
    -------
    game_data: The characters, stage, and winners for each game in all events
    """

    query = '''query EventSets($eventId: ID!, $page: Int!) {
                 event(id: $eventId) {
                   id
                   name
                   sets(
                     page: $page
                     perPage: 25
                     sortType: NONE
                   ) {
                     pageInfo {
                       total
                     }
                     nodes {
                       id
                       winnerId
                       slots {
                         id
                         entrant {
                           id
                         }
                       }
                       games {
                         winnerId
                         stage {
                           name
                         }
                         selections {
                           entrant {
                             id
                             name
                             participants {
                               id
                             }
                           }
                           selectionType
                           selectionValue
                         }
                       }
                     }
                   }
                 }
               }
            '''

    game_data = {'char1': [],
                 'char2': [],
                 'stage': [],
                 'winner': [],
                 'entrant1': [],
                 'entrant2': [],
                }

    for event_id in event_ids:
        i = 1
        done_paginating = False
        while not done_paginating:
            parameters = {'eventId': event_id, 'page': i}
            result = call_api(query, parameters, client)

            sets = result['data']['event']['sets']['nodes']
            set_count = 0
            try:
                set_count = result['data']['event']['sets']['pageInfo']['total']
            except TypeError:
                break
            if set_count == 0:
                break
            event_name = result['data']['event']['name']

            is_doubles = False
            for set_ in sets:
                # If no games were played, we don't care about the set
                if set_['games'] is None:
                    continue

                slots = set_['slots']

                # Get participant ids
                if not set_is_singles(slots):
                    is_doubles = True
                    break

                participant_ids = get_participant_ids(slots)

                games = set_['games']

                id_to_char = parse_id_to_char_file(ID_TO_CHAR_FILE)

                game_data = update_game_data(games, id_to_char, game_data)

            i += 1
            if is_doubles:
                break

    return game_data


def read_token(token_file):
    '''Read the auth token from a file'''
    with open(token_file, 'r') as in_file:
        token = in_file.readline().strip()

    return token


if __name__ == '__main__':
    token = read_token(TOKEN_FILE)

    client = GraphQLClient(API_URL + API_VERSION)
    client.inject_token('Bearer ' + token)

    sys.stderr.write('Finding all smash ultimate events\n')
    event_ids = get_ultimate_events(client)
    sys.stderr.write('Parsing event data\n')
    game_data = get_sets_for_events(event_ids)

    data_df = pd.DataFrame.from_dict(game_data)
    data_df.to_csv(OUT_FILE)
