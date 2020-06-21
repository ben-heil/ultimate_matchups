# Analyze char vs character matchups
# Analyze which stages are good for a character in general
# If there's enough data, analyze stages for a character against other chars
import json
import sys

from graphqlclient import GraphQLClient
import pandas as pd
import ratelimiter

# TODO this should be a config file
TOKEN_FILE = 'token.txt'
ID_TO_CHAR_FILE = 'character_to_id.csv'
OUT_FILE = 'game_data.csv'
API_URL = 'https://api.smash.gg/gql/'
API_VERSION = 'alpha'
ULTIMATE_ID = 1386 # This is smash.gg's internal representation of smash ultimate

def parse_id_to_char_file(in_file):
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
    result = json.loads(client.execute(query, params))

    return result


def event_is_ultimate(event: dict) -> bool:
    ''' Determine whether an event object returned from smashgg's API is
    an event where the players are playing Smash Ultimate

    Arguments
    ---------
    event: The json returned from the graphQL query containing information about the event

    Returns
    -------
    is_ultimate: Whether the event is a Smash Ultimate event
    '''
    try:
        game_id = event['videogame']['id']
        return game_id == ULTIMATE_ID
    except KeyError:
        return False


def get_ultimate_events(client):
    # TODO implement logic to iterate over all tourneys
    # Done is denoted by result.data.tournaments.nodes being None
    event_ids = set()
    query = '''query TournamentsByVideogame($perPage: Int!, $videogameId: ID!, $page: Int!) {
                tournaments(query: {
                    perPage: $perPage
                    page: $page
                    sortBy: "startAt asc"
                    filter: {
                    past: false
                    videogameIds: [
                        $videogameId
                    ]
                    }
                }) {
                    nodes {
                      id
                      name
                      events(limit: 100) {
                        id
                        name
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
    i = 1
    while not done_iterating:
        parameters = {'page': i, 'perPage': 20, 'videogameId': ULTIMATE_ID}

        result = call_api(query, parameters, client)

        tournaments = result['data']['tournaments']['nodes']
        if tournaments is None:
            done_iterating = True
            break

        for tournament in tournaments:
            events = tournament['events']
            for event in events:
                # Keep only smash ultimate online matches from completed events
                if not event_is_ultimate(event):
                    continue
                if not event['isOnline']:
                    continue
                if not event['state'] == 'COMPLETED':
                    continue
                event_ids.add(event['id'])
        i += 1
    return event_ids


def set_is_singles(slots):
    """Check whether a set is in the singles or doubles format based on its slots"""
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
    if selection['entrant'] is None:
        return None, None
    entrant_id = selection['entrant']['id']

    character_id = selection['selectionValue']
    character_name = None
    if character_id in id_to_char:
        character_name = id_to_char[character_id]
    else:
        sys.stderr.write('Character with id {} is not in the file\n'.format(character_id))

    return entrant_id, character_name


def update_game_data(games, id_to_char, game_data):
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
        for selection in game_selections:
            if selection['selectionType'] != 'CHARACTER':
                continue
            if first_selection:
                entrant1, char1 = parse_selection(game_selections[0], id_to_char)
                first_selection = False
            else:
                entrant2, char2 = parse_selection(game_selections[1], id_to_char)

        if entrant1 == winner:
            game_data['char1'].append(char1)
            game_data['char2'].append(char2)
            game_data['winner'].append(char1)
            game_data['stage'].append(stage)
        elif entrant2 == winner:
            game_data['char1'].append(char1)
            game_data['char2'].append(char2)
            game_data['winner'].append(char2)
            game_data['stage'].append(stage)
        else:
            if char1 is not None and char2 is not None:
                sys.stderr.write('Something went wrong in winner parsing\n')


    return game_data


def get_sets_for_events(event_ids: list) -> dict:
    ''' Query each event and download its associated data

    Arguments
    ---------
    event_ids: the identifiers allowing us to select each smash ultimate event

    Returns
    -------
    game_data: The characters, stage, and winners for each game in all events
    '''

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
                           name
                         }
                       }
                       games {
                         id
                         winnerId
                         stage {
                           name
                         }
                         selections {
                           entrant {
                             id
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
                 'winner': []
                }

    for event_id in event_ids:
        i = 1
        done_paginating = False
        while not done_paginating:
            parameters = {'eventId': event_id, 'page': i}
            result = call_api(query, parameters, client)

            sets = result['data']['event']['sets']['nodes']
            set_count = result['data']['event']['sets']['pageInfo']['total']
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




                # Get characters
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
