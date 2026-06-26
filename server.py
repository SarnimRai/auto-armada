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
active_connections = {}

@app.route('/')
def home():
    return render_template('index.html')

# --- SOCKET EVENTS ---

@socketio.on('create_room')
def handle_create_room(data):
    username = data['username']
    room_code = data['roomCode']
    join_room(room_code)
    
    # NEW: Track this specific user's connection for disconnect handling
    active_connections[request.sid] = {'room': room_code, 'username': username}
    
    # Track host initialization metrics inside the player map matrix
    live_rooms[room_code] = {
        'host': username,
        'players': [username],
        'player_states': {
            username: { 'color': '#ff4444', 'ready': False } # Default initial color assignments
        },
        'perks_ready': 0  
    }
    emit('room_update', {'roomCode': room_code, 'players': live_rooms[room_code]['players'], 'host': username}, to=request.sid)

@socketio.on('join_room')
def handle_join_room(data):
    username = data['username']
    room_code = data['roomCode']
    if room_code in live_rooms:
        if len(live_rooms[room_code]['players']) < 4:
            join_room(room_code)
            live_rooms[room_code]['players'].append(username)
            
            # NEW: Track this specific user's connection
            active_connections[request.sid] = {'room': room_code, 'username': username}
            
            # Auto-assign an unoccupied starting slot structure
            live_rooms[room_code]['player_states'][username] = { 'color': '#44aaff', 'ready': False }
            
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
        
        # NEW: Track this specific user's connection
        active_connections[request.sid] = {'room': target_room, 'username': username}
        
        live_rooms[target_room]['player_states'][username] = { 'color': '#ffcc00', 'ready': False }
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
        room = live_rooms[room_code]
        players_list = room['players']
        
        # Extract the globally synchronized colors based on the exact player order
        ordered_colors = []
        for p in players_list:
            ordered_colors.append(room['player_states'][p]['color'])
            
        # Append AI colors (Pink) if the host added bots
        ai_count = int(data.get('aiCount', 0))
        for i in range(ai_count):
            ordered_colors.append('#ff00ff') 
            
        payload = {
            'seed': room_code + str(random.randint(1000, 9999)),
            'playerCount': len(players_list),
            'aiCount': ai_count,
            'playersList': players_list,
            'factionColors': ordered_colors, # The universal color fix!
            'rounds': int(data.get('rounds', 3)),
            'ships': int(data.get('ships', 30))
        }
        
        # Step 1: Tell everyone to load the UI and prepare memory
        emit('prepare_match', payload, to=room_code)
        
        # Step 2: Buffer time. This defeats the network latency imbalance!
        eventlet.sleep(2.5) 
        
        # Step 3: Fire the starting gun for all clients simultaneously
        emit('begin_match_physics', {}, to=room_code)

@socketio.on('perk_selected')
def handle_perk_selected(data):
    room_code = data['roomCode']
    if room_code in live_rooms:
        live_rooms[room_code]['perks_ready'] = live_rooms[room_code].get('perks_ready', 0) + 1
        if live_rooms[room_code]['perks_ready'] >= len(live_rooms[room_code]['players']):
            live_rooms[room_code]['perks_ready'] = 0
            
            # Buffer the perk resume so everyone starts the new round together!
            eventlet.sleep(1.5)
            emit('resume_round', {}, to=room_code)

@socketio.on('update_sliders')
def handle_slider_update(data):
    room_code = data['roomCode']
    # MULTIPLAYER SYNC FIX: Bounce the update to EVERYONE, including the sender!
    emit('peer_slider_update', data, to=room_code)


@socketio.on('sync_color_change')
def handle_sync_color_change(data):
    room_code = data['roomCode']
    username = data['username']
    chosen_color = data['color']
    
    if room_code in live_rooms and username in live_rooms[room_code]['player_states']:
        live_rooms[room_code]['player_states'][username]['color'] = chosen_color
        # Broadcast full structural changes back down to all room peers
        emit('lobby_config_update', {'states': live_rooms[room_code]['player_states']}, to=room_code)

@socketio.on('sync_ready_toggle')
def handle_sync_ready_toggle(data):
    room_code = data['roomCode']
    username = data['username']
    
    if room_code in live_rooms and username in live_rooms[room_code]['player_states']:
        current_status = live_rooms[room_code]['player_states'][username]['ready']
        live_rooms[room_code]['player_states'][username]['ready'] = not current_status
        emit('lobby_config_update', {'states': live_rooms[room_code]['player_states']}, to=room_code)

@socketio.on('transmit_chat_message')
def handle_transmit_chat_message(data):
    room_code = data['roomCode']
    payload = {
        'sender': data['username'],
        'msg': data['message']
    }
    emit('receive_room_chat', payload, to=room_code)

@socketio.on('add_ai_bot')
def handle_add_ai_bot(data):
    room_code = data['roomCode']
    if room_code in live_rooms:
        # Tally existing bots
        ai_count = sum(1 for name in live_rooms[room_code]['player_states'] if name.startswith('AI BOT'))
        
        if ai_count < 2:
            bot_name = f"AI BOT {ai_count + 1}"
            # Inject a permanently 'ready' bot into the synchronization matrix
            live_rooms[room_code]['player_states'][bot_name] = {'color': '#ff00ff', 'ready': True, 'is_ai': True}
            
            # Immediately broadcast the new roster to all players
            emit('lobby_config_update', {'states': live_rooms[room_code]['player_states']}, to=room_code)

@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in active_connections:
        conn = active_connections[request.sid]
        room_code = conn['room']
        username = conn['username']
        
        if room_code in live_rooms:
            room = live_rooms[room_code]
            if username in room['players']:
                room['players'].remove(username)
                if username in room['player_states']:
                    del room['player_states'][username]
                
                # Tell everyone else in the room that this player retreated!
                emit('player_left', {'username': username, 'remaining': len(room['players'])}, to=room_code)
                
                # If everyone leaves, delete the room from the server memory
                if len(room['players']) == 0:
                    del live_rooms[room_code]
                    
        del active_connections[request.sid]