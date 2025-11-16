from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import datetime

def generate_self_signed_cert():
    """
    Génère une clé privée et un certificat auto-signé.
    """
    # 1. Générer une clé privée
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # 2. Créer les informations du sujet (pour le certificat)
    # Pour un certificat auto-signé, le sujet et l'émetteur sont les mêmes.
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"California"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, u"San Francisco"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"My Company"),
        # IMPORTANT: Le nom commun doit être le domaine ou l'IP que le client utilisera.
        # Pour des tests en local, 'localhost' est parfait.
        x509.NameAttribute(NameOID.COMMON_NAME, u"localhost"),
    ])

    # 3. Construire le certificat
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        private_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.utcnow()
    ).not_valid_after(
        # Le certificat sera valide pour 1 an
        datetime.datetime.utcnow() + datetime.timedelta(days=365)
    ).add_extension(
        x509.SubjectAlternativeName([x509.DNSName(u"localhost")]),
        critical=False,
    # Signer le certificat avec notre clé privée
    ).sign(private_key, hashes.SHA256())

    # 4. Écrire la clé privée dans un fichier (key.pem)
    with open("key.pem", "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    print("Clé privée générée : key.pem")

    # 5. Écrire le certificat dans un fichier (cert.pem)
    with open("cert.pem", "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    print("Certificat généré : cert.pem")

if __name__ == "__main__":
    generate_self_signed_cert()
