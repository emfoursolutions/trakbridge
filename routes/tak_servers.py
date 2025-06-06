# =============================================================================
# routes/tak_servers.py - TAK Server Routes
# =============================================================================

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from database import db

bp = Blueprint('tak_servers', __name__)


@bp.route('/')
def list_tak_servers():
    """List all TAK servers"""
    from models.tak_server import TakServer
    servers = TakServer.query.all()
    return render_template('tak_servers.html', servers=servers)


@bp.route('/create', methods=['GET', 'POST'])
def create_tak_server():
    """Create a new TAK server"""
    if request.method == 'GET':
        return render_template('create_tak_server.html')

    from models.tak_server import TakServer
    data = request.get_json() if request.is_json else request.form

    try:
        # Handle verify_ssl for both form data (string) and JSON data (boolean)
        verify_ssl_value = data.get('verify_ssl', True)
        if isinstance(verify_ssl_value, str):
            verify_ssl = verify_ssl_value.lower() == 'true'
        elif isinstance(verify_ssl_value, bool):
            verify_ssl = verify_ssl_value
        else:
            verify_ssl = True  # Default to True

        server = TakServer(
            name=data['name'],
            host=data['host'],
            port=int(data['port']),
            protocol=data.get('protocol', 'tls'),
            cert_pem=data.get('cert_pem', ''),
            cert_key=data.get('cert_key', ''),
            client_password=data.get('client_password', ''),
            verify_ssl=verify_ssl
        )

        db.session.add(server)
        db.session.commit()

        if request.is_json:
            return jsonify({'success': True, 'server_id': server.id})
        else:
            flash('TAK Server created successfully', 'success')
            return redirect(url_for('tak_servers.list_tak_servers'))

    except Exception as e:
        db.session.rollback()
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 400
        else:
            flash(f'Error creating TAK server: {str(e)}', 'error')
            return redirect(url_for('tak_servers.create_tak_server'))


@bp.route('/<int:server_id>')
def view_tak_server(server_id):
    """View TAK server details"""
    from models.tak_server import TakServer
    server = TakServer.query.get_or_404(server_id)
    return render_template('tak_server_detail.html', server=server)


@bp.route('/<int:server_id>/edit', methods=['GET', 'POST'])
def edit_tak_server(server_id):
    """Edit TAK server"""
    from models.tak_server import TakServer
    server = TakServer.query.get_or_404(server_id)

    if request.method == 'GET':
        return render_template('edit_tak_server.html', server=server)

    data = request.get_json() if request.is_json else request.form

    try:
        # Handle verify_ssl for both form data (string) and JSON data (boolean)
        verify_ssl_value = data.get('verify_ssl', True)
        if isinstance(verify_ssl_value, str):
            verify_ssl = verify_ssl_value.lower() == 'true'
        elif isinstance(verify_ssl_value, bool):
            verify_ssl = verify_ssl_value
        else:
            verify_ssl = True  # Default to True

        server.name = data['name']
        server.host = data['host']
        server.port = int(data['port'])
        server.protocol = data.get('protocol', 'tls')
        server.cert_pem = data.get('cert_pem', '')
        server.cert_key = data.get('cert_key', '')
        server.client_password = data.get('client_password', '')
        server.verify_ssl = verify_ssl

        db.session.commit()

        if request.is_json:
            return jsonify({'success': True})
        else:
            flash('TAK Server updated successfully', 'success')
            return redirect(url_for('tak_servers.view_tak_server', server_id=server_id))

    except Exception as e:
        db.session.rollback()
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 400
        else:
            flash(f'Error updating TAK server: {str(e)}', 'error')
            return redirect(url_for('tak_servers.edit_tak_server', server_id=server_id))


@bp.route('/<int:server_id>/delete', methods=['DELETE'])
def delete_tak_server(server_id):
    """Delete TAK server"""
    try:
        from models.tak_server import TakServer
        server = TakServer.query.get_or_404(server_id)

        if server.streams:
            return jsonify({
                'success': False,
                'error': 'Cannot delete server with associated streams'
            }), 400

        db.session.delete(server)
        db.session.commit()

        return jsonify({'success': True, 'message': 'TAK Server deleted'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:server_id>/test', methods=['POST'])
def test_tak_server(server_id):
    """Test connection to TAK server"""
    from models.tak_server import TakServer
    server = TakServer.query.get_or_404(server_id)

    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((server.host, server.port))
        sock.close()

        if result == 0:
            return jsonify({'success': True, 'message': 'Connection successful'})
        else:
            return jsonify({'success': False, 'error': 'Connection failed'})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})