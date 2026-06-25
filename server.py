import eventlet
eventlet.monkey_patch()

import random
from flask import Flask, render_template
from flask_socketio import SocketIO, join_room, leave_room, emit
from flask import request

app = Flask(__name__)
app.config['SECRET_KEY'] = 'super_secret_armada_key'

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# This dictionary will store our live rooms in the server's memory
# Example: {'A1B2C3D4': {'host': 'Player1', 'players': ['Player1', 'Player2']}}
live_rooms = {}

@app.route('/')
def home():
    return render_template('index.html')

# --- SOCKET EVENTS ---

@socketio.on('create_room')
def handle_create_room(data):
    username = data['username']
    room_code = data['roomCode']
    join_room(room_code)
    live_rooms[room_code] = {
        'host': username,
        'players': [username],
        'perks_ready': 0  
    }
    # Direct targeting to request.sid cuts out processing room latency delays
    emit('room_update', {'roomCode': room_code, 'players': live_rooms[room_code]['players'], 'host': username}, to=request.sid)

@socketio.on('join_room')
def handle_join_room(data):
    username = data['username']
    room_code = data['roomCode']
    if room_code in live_rooms:
        if len(live_rooms[room_code]['players']) < 4:
            join_room(room_code)
            live_rooms[room_code]['players'].append(username)
            # Sends authoritative host string instead of a volatile boolean flag
            emit('room_update', {'roomCode': room_code, 'players': live_rooms[room_code]['players'], 'host': live_rooms[room_code]['host']}, to=room_code)
        else:
            emit('error_message', {'msg': 'Room is full! (Max 4 Pilots)'})
    else:
        emit('error_message', {'msg': 'Invalid Room Code!'})

@socketio.on('join_random_room')
def handle_join_random(data):
    username = data['username']
    open_rooms = [code for code, info in live_rooms.items() if len(info['players']) < 4]
    if open_rooms:
        target_room = random.choice(open_rooms)
        join_room(target_room)
        live_rooms[target_room]['players'].append(username)
        emit('room_update', {'roomCode': target_room, 'players': live_rooms[target_room]['players'], 'host': live_rooms[target_room]['host']}, to=target_room)
    else:
        emit('error_message', {'msg': 'No open rooms found! Please host a new match.'})


    # --- NEW MULTIPLAYER STATES ---

@socketio.on('go_to_config')
def handle_go_to_config(data):
    room_code = data['roomCode']
    # Tell everyone in the room to open the config screen.
    # Send 'isHost: False' to all the guests
    emit('show_config_screen', {'isHost': False}, to=room_code, include_self=False)
    # Send 'isHost: True' ONLY to the host who clicked the button
    emit('show_config_screen', {'isHost': True})

@socketio.on('launch_game')
def handle_launch_game(data):
    room_code = data['roomCode']
    if room_code in live_rooms:
        players_list = live_rooms[room_code]['players']
        
        # Broadcast to everyone in the room to start the match!
        emit('start_multiplayer_match', {
            'ships': int(data['ships']),
            'rounds': int(data['rounds']),
            'aiCount': int(data['aiCount']),
            'playerCount': len(players_list),
            'playersList': players_list, # Sending the list so frontend can calculate Faction IDs
            'seed': random.randint(1, 100000) # <-- NEW: Shared random seed for deterministic synchronization
        }, to=room_code)

@socketio.on('perk_selected')
def handle_perk_selected(data):
    room_code = data['roomCode']
    if room_code in live_rooms:
        live_rooms[room_code]['perks_ready'] += 1
        
        # Check if everyone has picked their perks
        if live_rooms[room_code]['perks_ready'] >= len(live_rooms[room_code]['players']):
            # Reset counter for the next round
            live_rooms[room_code]['perks_ready'] = 0
            # Tell everyone to resume the battle!
            emit('resume_round', to=room_code)

@socketio.on('update_sliders')
def handle_slider_update(data):
    room_code = data['roomCode']
    # Relay this player's slider metrics to every other peer in the room instantly
    emit('peer_slider_update', data, to=room_code, include_self=False)