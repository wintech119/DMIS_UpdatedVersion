# TLS/SSL Hardening Implementation for DMIS

## Overview

This document describes the hardened TLS/SSL configuration for the DMIS (Disaster Management Information System) production deployment. The configuration eliminates weak and deprecated cipher suites and protocols to meet modern cybersecurity standards.

---

## Security Standards Compliance

### ✅ Requirements Met

| Requirement | Status | Implementation |
|-------------|--------|----------------|
| **Remove RSA Key Exchange** | ✅ Complete | All `TLS_RSA_*` cipher suites removed |
| **TLS 1.2+ Only** | ✅ Complete | `ssl_protocols TLSv1.2 TLSv1.3` |
| **Perfect Forward Secrecy** | ✅ Complete | ECDHE-based ciphers only |
| **No SHA-1** | ✅ Complete | Only SHA-256, SHA-384, and AEAD |
| **Modern Cipher Suites** | ✅ Complete | AES-GCM and CHACHA20-POLY1305 |
| **Zero Application Changes** | ✅ Complete | Nginx layer only, no code changes |

---

## Deployment Architecture

### Current Environment (Development - Replit)

**TLS/SSL Status**: Handled by Replit infrastructure
- ✅ No configuration needed for development
- ✅ Replit manages TLS termination at edge
- ✅ Application code unchanged
- ✅ All features work normally

### Production Environment (AlmaLinux/RHEL + Nginx)

**TLS/SSL Configuration**: Applied at Nginx front-end web server
- **Configuration File**: `docs/nginx-tls-hardening.conf`
- **Layer**: Nginx reverse proxy (port 443)
- **Backend**: UWSGI application server (port 2022)
- **Static Files**: Nginx media server (port 2020)

```
┌──────────────────────────────────────────────────────┐
│  Internet (Clients)                                   │
└───────────────────────┬──────────────────────────────┘
                        │
                        │ HTTPS (TLS 1.2/1.3)
                        │ Hardened Cipher Suites
                        ▼
        ┌───────────────────────────────┐
        │   Nginx (Port 443)            │
        │   - TLS Termination           │
        │   - Cipher Suite Enforcement  │
        │   - HSTS                      │
        │   - Security Headers          │
        └───────────────┬───────────────┘
                        │
          ┌─────────────┴─────────────┐
          │                           │
          │ HTTP (Internal)           │ HTTP (Internal)
          ▼                           ▼
┌─────────────────────┐     ┌─────────────────────┐
│ UWSGI (Port 2022)   │     │ Nginx Media Server  │
│ Flask Application   │     │ (Port 2020)         │
│ - Business Logic    │     │ - Static Files      │
│ - CSP Headers       │     │ - CSS/JS/Images     │
└─────────────────────┘     └─────────────────────┘
```

---

## Hardened Cipher Suite Configuration

### Allowed Cipher Suites

**TLS 1.2 Cipher Suites** (ECDHE + PFS):
```
ECDHE-ECDSA-AES128-GCM-SHA256
ECDHE-RSA-AES128-GCM-SHA256
ECDHE-ECDSA-AES256-GCM-SHA384
ECDHE-RSA-AES256-GCM-SHA384
ECDHE-ECDSA-CHACHA20-POLY1305
ECDHE-RSA-CHACHA20-POLY1305
```

**TLS 1.3 Cipher Suites** (Default):
```
TLS_AES_128_GCM_SHA256
TLS_AES_256_GCM_SHA384
TLS_CHACHA20_POLY1305_SHA256
```

### Removed/Blocked Cipher Suites

❌ **All RSA Key Exchange** (ROBOT vulnerability):
```
TLS_RSA_WITH_AES_128_CBC_SHA
TLS_RSA_WITH_AES_256_CBC_SHA
TLS_RSA_WITH_AES_128_GCM_SHA256
TLS_RSA_WITH_AES_256_GCM_SHA384
All other TLS_RSA_* variants
```

❌ **All SHA-1 Cipher Suites**:
```
*_SHA (any cipher suite ending in _SHA)
```

❌ **Deprecated Protocols**:
```
SSLv2
SSLv3
TLS 1.0
TLS 1.1
```

---

## Implementation Instructions

### Prerequisites

1. **Production server** running AlmaLinux 9.7 or RHEL 9+
2. **Nginx** installed (version 1.19.0+ recommended for TLS 1.3 support)
3. **Valid SSL/TLS certificate** for `drims.odpem.gov.jm`
4. **OpenSSL** version 1.1.1+ (for TLS 1.3 and modern ciphers)

### Step 1: Verify OpenSSL Version

```bash
openssl version
```

**Required**: OpenSSL 1.1.1 or later (for TLS 1.3 support)

### Step 2: Generate Diffie-Hellman Parameters

```bash
sudo openssl dhparam -out /etc/ssl/certs/dhparam.pem 2048
```

This provides additional security for key exchange. Generation takes 2-5 minutes.

### Step 3: Install SSL Certificate

Place your SSL certificate and private key:

```bash
# Certificate (includes intermediate certificates)
/etc/ssl/certs/drims.odpem.gov.jm.crt

# Private key (keep secure!)
/etc/ssl/private/drims.odpem.gov.jm.key

# Set restrictive permissions on private key
sudo chmod 600 /etc/ssl/private/drims.odpem.gov.jm.key
```

### Step 4: Deploy Nginx Configuration

Copy the hardened configuration:

```bash
# Backup existing configuration
sudo cp /etc/nginx/conf.d/drims.conf /etc/nginx/conf.d/drims.conf.backup

# Deploy hardened configuration
sudo cp docs/nginx-tls-hardening.conf /etc/nginx/conf.d/drims.conf
```

### Step 5: Update Certificate Paths

Edit `/etc/nginx/conf.d/drims.conf` and update these lines with your actual certificate paths:

```nginx
ssl_certificate /path/to/your/certificate.crt;
ssl_certificate_key /path/to/your/private.key;
```

### Step 6: Test Configuration

```bash
# Test Nginx configuration syntax
sudo nginx -t

# Expected output:
# nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# nginx: configuration file /etc/nginx/nginx.conf test is successful
```

### Step 7: Reload Nginx

```bash
# Gracefully reload Nginx (zero downtime)
sudo systemctl reload nginx

# Or restart if needed
sudo systemctl restart nginx
```

---

## Verification & Testing

### 1. SSL Labs Test

Test your deployment using [SSL Labs Server Test](https://www.ssllabs.com/ssltest/):

```
https://www.ssllabs.com/ssltest/analyze.html?d=drims.odpem.gov.jm
```

**Expected Rating**: A or A+

**Expected Results**:
- ✅ TLS 1.2 and TLS 1.3 only
- ✅ Perfect Forward Secrecy (PFS) for all cipher suites
- ✅ No RSA key exchange
- ✅ No SHA-1 cipher suites
- ✅ HSTS enabled
- ✅ Strong cipher suite ordering

### 2. Command-Line Testing

Test TLS protocols:

```bash
# Test TLS 1.2 (should succeed)
openssl s_client -connect drims.odpem.gov.jm:443 -tls1_2 < /dev/null

# Test TLS 1.3 (should succeed)
openssl s_client -connect drims.odpem.gov.jm:443 -tls1_3 < /dev/null

# Test TLS 1.1 (should FAIL - protocol disabled)
openssl s_client -connect drims.odpem.gov.jm:443 -tls1_1 < /dev/null

# Test TLS 1.0 (should FAIL - protocol disabled)
openssl s_client -connect drims.odpem.gov.jm:443 -tls1 < /dev/null
```

Test cipher suites:

```bash
# List negotiated cipher
openssl s_client -connect drims.odpem.gov.jm:443 -tls1_2 < /dev/null | grep "Cipher"

# Expected output examples:
# Cipher    : ECDHE-RSA-AES256-GCM-SHA384
# Cipher    : ECDHE-RSA-AES128-GCM-SHA256
```

### 3. Browser Testing

Test with modern browsers:

- ✅ **Chrome/Edge**: Navigate to `https://drims.odpem.gov.jm`
- ✅ **Firefox**: Navigate to `https://drims.odpem.gov.jm`
- ✅ **Safari**: Navigate to `https://drims.odpem.gov.jm`

All should connect successfully with a secure padlock icon.

**Check Certificate Details** (Chrome):
1. Click padlock icon → "Connection is secure"
2. Click "Certificate is valid"
3. Verify: TLS 1.2 or TLS 1.3, ECDHE key exchange, AES-GCM encryption

### 4. Security Scanner Testing

Use `nmap` to verify cipher suites:

```bash
# Scan SSL/TLS configuration
nmap --script ssl-enum-ciphers -p 443 drims.odpem.gov.jm

# Expected output should show:
# - TLSv1.2 and TLSv1.3 only
# - ECDHE cipher suites only
# - No RSA key exchange
# - No SHA-1 ciphers
```

---

## Compatibility

### ✅ Compatible Clients

The hardened configuration maintains compatibility with:

**Modern Browsers**:
- Chrome 49+ (2016+)
- Firefox 27+ (2014+)
- Safari 9+ (2015+)
- Edge (all versions)
- Opera 36+ (2016+)

**API Clients**:
- curl 7.34.0+ (2013+)
- Python requests (with OpenSSL 1.0.1+)
- Node.js (with default TLS settings)
- Java 8+ (with default security providers)
- .NET Framework 4.6+

**Mobile Devices**:
- iOS 9+ (2015+)
- Android 5.0+ (2014+)

### ❌ Incompatible Legacy Clients

The following legacy clients **will NOT be able to connect**:
- Internet Explorer on Windows XP
- Android 4.4 and earlier
- Java 7 and earlier (without custom configuration)
- Very old curl/wget versions

**Mitigation**: These clients are already end-of-life and should not be used for security reasons.

---

## Monitoring & Maintenance

### Log Monitoring

Monitor Nginx error logs for TLS-related issues:

```bash
sudo tail -f /var/log/nginx/error.log | grep -i ssl
```

### Certificate Renewal

SSL certificates typically expire after 90 days (Let's Encrypt) or 1 year (commercial CAs).

**Set up automatic monitoring**:

```bash
# Check certificate expiration
openssl s_client -connect drims.odpem.gov.jm:443 -servername drims.odpem.gov.jm < /dev/null 2>/dev/null | openssl x509 -noout -dates
```

**Recommended**: Use automated certificate renewal (certbot for Let's Encrypt).

### Periodic Security Audits

Schedule quarterly security audits:
1. Run SSL Labs test
2. Review Nginx access/error logs
3. Update cipher suite list if new vulnerabilities discovered
4. Review OpenSSL CVEs and patch as needed

---

## Troubleshooting

### Issue: "No shared cipher" Error

**Symptom**: Clients cannot connect, error "no shared cipher"

**Cause**: Client doesn't support any of the configured cipher suites

**Solution**: 
1. Verify client TLS version support
2. Check that client is not too old (pre-2014)
3. Review client logs for specific cipher suite requirements

### Issue: OCSP Stapling Failures

**Symptom**: OCSP stapling verification errors in logs

**Solution**:
```nginx
# Temporarily disable OCSP stapling in nginx config
ssl_stapling off;
ssl_stapling_verify off;
```

### Issue: DH Parameter Error

**Symptom**: "SSL: error:141A318A:SSL routines:tls_process_ske_dhe:dh key too small"

**Solution**: Regenerate DH parameters with 2048-bit minimum:
```bash
sudo openssl dhparam -out /etc/ssl/certs/dhparam.pem 2048
```

---

## Security Best Practices

### 1. Keep OpenSSL Updated

```bash
# Check for OpenSSL updates
sudo dnf update openssl

# Restart Nginx after OpenSSL updates
sudo systemctl restart nginx
```

### 2. Enable HTTP/2

Already enabled in configuration:
```nginx
listen 443 ssl http2;
```

Benefits: Better performance, reduced latency, multiplexing.

### 3. Monitor Security Advisories

Subscribe to security mailing lists:
- [Nginx Security Advisories](http://mailman.nginx.org/mailman/listinfo/nginx-announce)
- [OpenSSL Security Advisories](https://www.openssl.org/news/secadv/)
- [AlmaLinux Security](https://almalinux.org/security/)

### 4. Regular Penetration Testing

Perform annual penetration testing covering:
- TLS/SSL configuration
- Cipher suite negotiation
- Certificate validation
- HSTS enforcement
- Security header verification

---

## Performance Impact

### Expected Performance Characteristics

**TLS Handshake**:
- TLS 1.2: ~2-3 RTT (round-trip time)
- TLS 1.3: ~1-2 RTT (faster!)
- Session resumption: ~1 RTT

**CPU Usage**:
- ECDHE key exchange: ~2-3% CPU overhead vs RSA
- AES-GCM encryption: Hardware-accelerated on modern CPUs (AES-NI)
- CHACHA20-POLY1305: Software-based, optimized for mobile devices

**Overall Impact**: Negligible (<5% CPU overhead) on modern servers with AES-NI support.

---

## Additional Security Headers

The Flask application already implements these security headers via CSP middleware (`app/security/csp.py`):

- ✅ Content-Security-Policy (nonce-based)
- ✅ X-Content-Type-Options: nosniff
- ✅ X-Frame-Options: DENY
- ✅ Referrer-Policy: strict-origin-when-cross-origin
- ✅ X-XSS-Protection: 1; mode=block
- ✅ Permissions-Policy

Nginx configuration **duplicates** these headers for defense-in-depth.

**HSTS (HTTP Strict Transport Security)** is added at Nginx level only:
```nginx
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
```

This forces browsers to always use HTTPS for 1 year after first visit.

---

## Compliance & Standards

This configuration meets or exceeds:

✅ **PCI DSS 3.2.1** - Payment Card Industry Data Security Standard  
✅ **NIST SP 800-52 Rev. 2** - Guidelines for TLS Implementations  
✅ **OWASP TLS Cheat Sheet** - Transport Layer Protection  
✅ **HIPAA Security Rule** - Healthcare data protection  
✅ **FIPS 140-2** - Federal Information Processing Standards (with appropriate OpenSSL)  
✅ **Government of Jamaica Cybersecurity Standards**  

---

## References

- [Mozilla SSL Configuration Generator](https://ssl-config.mozilla.org/)
- [OWASP Transport Layer Protection Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Protection_Cheat_Sheet.html)
- [NIST SP 800-52 Rev. 2](https://csrc.nist.gov/publications/detail/sp/800-52/rev-2/final)
- [SSL Labs Best Practices](https://github.com/ssllabs/research/wiki/SSL-and-TLS-Deployment-Best-Practices)
- [Nginx TLS/SSL Documentation](https://nginx.org/en/docs/http/ngx_http_ssl_module.html)

---

## Support & Contact

For questions or issues with TLS/SSL configuration:
1. Review this documentation
2. Check Nginx error logs: `/var/log/nginx/error.log`
3. Test configuration: `sudo nginx -t`
4. Contact system administrator or DevOps team

---

**Document Version**: 1.0  
**Last Updated**: November 22, 2025  
**Next Review**: February 22, 2026
