"""The development server's --https option: a self-signed certificate so a phone on the same Wi-Fi
gets a secure page, because browsers only open the microphone on https or localhost."""
import ipaddress

from cryptography import x509

from backend.synthetic import serve


def test_the_certificate_names_localhost_and_the_lan_address(tmp_path):
    cert, key = serve.dev_certificate(tmp_path, ["192.168.1.20"])
    loaded = x509.load_pem_x509_certificate(cert.read_bytes())
    names = loaded.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "localhost" in names.get_values_for_type(x509.DNSName)
    addresses = names.get_values_for_type(x509.IPAddress)
    assert ipaddress.ip_address("127.0.0.1") in addresses
    assert ipaddress.ip_address("192.168.1.20") in addresses
    assert key.read_bytes().startswith(b"-----BEGIN")


def test_the_certificate_is_reused_while_it_covers_the_same_addresses(tmp_path):
    first, _ = serve.dev_certificate(tmp_path, ["192.168.1.20"])
    made = first.read_bytes()
    again, _ = serve.dev_certificate(tmp_path, ["192.168.1.20"])
    assert again.read_bytes() == made  # a phone that accepted it once isn't asked again
    moved, _ = serve.dev_certificate(tmp_path, ["10.0.0.5"])
    assert moved.read_bytes() != made  # a new Wi-Fi address needs a certificate that names it
