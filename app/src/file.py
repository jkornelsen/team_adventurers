import os
import datetime
import tempfile
from types import SimpleNamespace
from flask import (
    g,
    json,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for
)
from werkzeug.utils import secure_filename

from src.game_data import GameData
from src.db_serializable import DbSerializable
from src.overall import Overall

def generate_filename(title):
    # Remove special characters and replace with '_'
    filename = ''.join(c if c.isalnum() else '_' for c in title)
    MAX_FILENAME_LENGTH = 30
    filename = filename[:MAX_FILENAME_LENGTH]  # Limit filename length
    filename = "{}.json".format(filename)
    return filename

def load_scenario_metadata(filepath):
    with open(filepath, 'r') as infile:
        data = json.load(infile)
    overall = Overall.from_json(data['overall'])
    return {
        'title': overall.title,
        'description': overall.description,
        'filename': os.path.basename(filepath)
    }

def load_data_from_file(filepath):
    with open(filepath, 'r') as infile:
        data = json.load(infile)
        GameData.clear_db_for_token()
        g.game_data = GameData.from_json(data)
    g.game_data.to_db()
    session['file_message'] = 'Loaded from file.'

def set_routes(app):
    @app.route('/configure')
    def configure():
        file_message = session.pop('file_message', False)
        GameData.entity_names_from_db()
        return render_template(
            'configure/index.html',
            game_data=g.game_data,
            file_message=file_message)

    @app.route('/save_to_file')
    def save_to_file():
        game_data = GameData.from_db()
        data_to_save = game_data.to_json()
        filename = generate_filename(game_data.overall.title)
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_file:
            filepath = temp_file.name
            json.dump(data_to_save, temp_file, indent=4)
        return send_file(filepath, as_attachment=True, download_name=filename)

    @app.route('/load_from_file', methods=['GET', 'POST'])
    def load_from_file():
        UPLOAD_DIR = app.config['UPLOAD_DIR']
        if request.method == 'GET':
            return render_template('session/upload.html')
        uploaded_file = request.files['file']
        if not uploaded_file.filename.endswith('.json'):
            return "Please upload a file with .json extension."
        filename = secure_filename(uploaded_file.filename)
        filepath = os.path.join(UPLOAD_DIR, filename)
        uploaded_file.save(filepath)
        load_data_from_file(filepath)
        # Get rid of old files
        MAX_FILE_AGE = datetime.timedelta(minutes=5)
        current_time = datetime.datetime.now()
        for filename in os.listdir(UPLOAD_DIR):
            file_path = os.path.join(UPLOAD_DIR, filename)
            file_mtime = datetime.datetime.fromtimestamp(os.path.getmtime(file_path))
            file_age = current_time - file_mtime
            if file_age > MAX_FILE_AGE:
                os.remove(file_path)
                print(f"Deleted {filename} (age: {file_age})")
        return redirect(url_for('configure'))

    @app.route('/browse_scenarios', methods=['GET', 'POST'])
    def browse_scenarios():
        DATA_DIR = app.config['DATA_DIR']
        if request.method == 'GET':
            scenarios = []
            for filename in os.listdir(DATA_DIR):
                if filename.endswith('.json'):
                    filepath = os.path.join(DATA_DIR, filename)
                    scenario = load_scenario_metadata(filepath)
                    scenarios.append(scenario)
            scenarios = sorted(scenarios, key=lambda sc: sc['filename'])
            return render_template(
                'configure/scenarios.html',
                scenarios=scenarios)
        scenario_file = request.form.get('scenario_file')
        scenario_title = request.form.get('scenario_title')
        if scenario_file:
            filepath = os.path.join(DATA_DIR, scenario_file)
            load_data_from_file(filepath)
            session['file_message'] = 'Loaded scenario "{}"'.format(scenario_title)
            return redirect(url_for('configure'))

    @app.route('/blank_scenario')
    def blank_scenario():
        GameData.clear_db_for_token()
        g.game_data = GameData()
        g.game_data.to_db()
        session['file_message'] = 'Starting game with default setup.'
        return redirect(url_for('configure'))

