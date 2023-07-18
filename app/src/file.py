import os
import tempfile
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
from tkinter import Tk, filedialog

from src.game_data import GameData
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
        g.game_data = GameData.from_json(data)
    g.game_data.to_db()
    session['file_message'] = 'Loaded from file.'
    return redirect(url_for('configure'))

def set_routes(app):
    @app.route('/save_to_file')
    def save_to_file():
        data_to_save = g.game_data.to_json()
        filename = generate_filename(g.game_data.overall.title)
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_file:
            filepath = temp_file.name
            json.dump(data_to_save, temp_file, indent=4)
        return send_file(filepath, as_attachment=True, attachment_filename=filename)

    @app.route('/load_from_file')
    def load_from_file():
        root = Tk()
        root.withdraw()
        filepath = filedialog.askopenfilename()
        if not filepath:
            # No file selected
            return redirect(url_for('configure'))
        return load_data_from_file(filepath)

    EXAMPLES_DIR = 'data'

    @app.route('/browse_scenarios', methods=['GET', 'POST'])
    def browse_scenarios():
        if request.method == 'POST':
            scenario_file = request.form.get('scenario_file')
            scenario_title = request.form.get('scenario_title')
            if scenario_file:
                filepath = os.path.join(EXAMPLES_DIR, scenario_file)
                load_data_from_file(filepath)
                session['file_message'] = 'Loaded scenario "{}"'.format(scenario_title)
                return redirect(url_for('configure'))
        scenarios = []
        for filename in os.listdir(EXAMPLES_DIR):
            if filename.endswith('.json'):
                filepath = os.path.join(EXAMPLES_DIR, filename)
                scenario = load_scenario_metadata(filepath)
                scenarios.append(scenario)
        return render_template('configure/scenarios.html', scenarios=scenarios)

