# =============================================================================
# models/tak_server.py - TAK Server Model
# =============================================================================

from database import db, TimestampMixin


class TakServer(db.Model, TimestampMixin):
    __tablename__ = 'tak_servers'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    host = db.Column(db.String(255), nullable=False)
    port = db.Column(db.Integer, nullable=False)
    protocol = db.Column(db.String(10), nullable=False, default='tls')

    # TLS Configuration
    cert_pem = db.Column(db.Text)
    cert_key = db.Column(db.Text)
    client_password = db.Column(db.String(255))
    verify_ssl = db.Column(db.Boolean, default=True)

    # Use back_populates instead of backref to match Stream model
    streams = db.relationship('Stream', back_populates='tak_server', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<TakServer {self.name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'host': self.host,
            'port': self.port,
            'protocol': self.protocol,
            'verify_ssl': self.verify_ssl,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

    def get_pytak_config(self):
        """Generate PyTAK configuration for this server"""
        config = {
            'COT_URL': f'{self.protocol}://{self.host}:{self.port}',
            'PYTAK_TLS_DONT_VERIFY': not self.verify_ssl
        }

        if self.cert_pem:
            config['PYTAK_TLS_CLIENT_CERT'] = self.cert_pem
        if self.cert_key:
            config['PYTAK_TLS_CLIENT_KEY'] = self.cert_key
        if self.client_password:
            config['PYTAK_TLS_CLIENT_PASSWORD'] = self.client_password

        return config