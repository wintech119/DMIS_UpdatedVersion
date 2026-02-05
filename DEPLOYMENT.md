# Needs List Wizard - Deployment Guide

## Overview

This guide covers deploying the new 3-step Needs List Wizard to production and migrating users from the legacy single-page preview component.

**Deployment Status**: Ready for Production
- ✅ All backend tests passing (3/3)
- ✅ All frontend tests passing (14/14)
- ✅ Both servers running successfully
- ✅ Multi-warehouse support implemented
- ✅ Backward compatibility maintained

---

## Pre-Deployment Checklist

### Backend Requirements
- [ ] PostgreSQL 16+ database configured
- [ ] Django 6.0+ installed
- [ ] Environment variables configured (see [Backend Configuration](#backend-configuration))
- [ ] Database migrations applied
- [ ] Static files collected
- [ ] CORS settings configured for frontend domain

### Frontend Requirements
- [ ] Node.js 18+ installed
- [ ] Angular CLI 18+ installed
- [ ] Production build tested locally
- [ ] API endpoint URLs updated for production
- [ ] Analytics/monitoring configured (optional)

### Infrastructure
- [ ] Web server configured (Nginx/Apache)
- [ ] SSL certificate installed
- [ ] Firewall rules configured
- [ ] Backup strategy in place
- [ ] Monitoring alerts configured

---

## Backend Configuration

### Environment Variables

Create a `.env` file in `backend/` directory:

```bash
# Required for Production
DJANGO_DEBUG=0
DJANGO_SECRET_KEY=<generate-secure-random-key>
DJANGO_ALLOWED_HOSTS=your-domain.com,www.your-domain.com

# Database Configuration
DB_NAME=dmis_production
DB_USER=dmis_user
DB_PASSWORD=<secure-password>
DB_HOST=localhost
DB_PORT=5432

# Legacy Database (for warehouse name resolution)
LEGACY_DB_NAME=legacy_inventory
LEGACY_DB_USER=readonly_user
LEGACY_DB_PASSWORD=<secure-password>
LEGACY_DB_HOST=legacy-db-server
LEGACY_DB_PORT=5432
LEGACY_DB_SCHEMA=public

# Optional
DJANGO_USE_SQLITE=0  # Set to 1 only for testing
```

### Generate Secure Secret Key

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### Database Setup

```bash
# Apply migrations
python manage.py migrate

# Create superuser (for admin access)
python manage.py createsuperuser

# Collect static files
python manage.py collectstatic --no-input

# Verify configuration
DJANGO_DEBUG=0 python manage.py check --deploy
```

### Test Backend API

```bash
# Start server
gunicorn backend.wsgi:application --bind 0.0.0.0:8000

# Test multi-warehouse endpoint
curl -X POST http://localhost:8000/api/v1/replenishment/needs-list/preview-multi \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"event_id": 1, "warehouse_ids": [1, 2], "phase": "BASELINE"}'
```

---

## Frontend Configuration

### Environment Files

**Production** (`frontend/src/environments/environment.prod.ts`):

```typescript
export const environment = {
  production: true,
  apiUrl: 'https://api.your-domain.com/api/v1',
  authUrl: 'https://keycloak.your-domain.com',
  enableWizard: true,  // Feature flag
  enableAnalytics: true
};
```

**Development** (`frontend/src/environments/environment.ts`):

```typescript
export const environment = {
  production: false,
  apiUrl: 'http://localhost:8000/api/v1',
  authUrl: 'http://localhost:8080',
  enableWizard: true,
  enableAnalytics: false
};
```

### Production Build

```bash
cd frontend

# Install dependencies
npm ci --production

# Run production build
ng build --configuration=production

# Output will be in dist/frontend/browser/
# Gzip size should be < 500KB for main bundle
```

### Build Verification

```bash
# Check bundle sizes
ls -lh dist/frontend/browser/*.js

# Expected output:
# main.*.js       ~300-400KB (gzipped ~80-100KB)
# polyfills.*.js  ~40-50KB
# styles.*.css    ~30-40KB
```

### Deploy Static Files

```bash
# Copy to web server
scp -r dist/frontend/browser/* user@server:/var/www/dmis/

# Or use nginx to serve
# nginx.conf example below
```

---

## Web Server Configuration

### Nginx Configuration

```nginx
# Frontend
server {
    listen 80;
    server_name dmis.your-domain.com;

    # Redirect to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name dmis.your-domain.com;

    ssl_certificate /etc/ssl/certs/dmis.crt;
    ssl_certificate_key /etc/ssl/private/dmis.key;

    root /var/www/dmis;
    index index.html;

    # Angular routing
    location / {
        try_files $uri $uri/ /index.html;

        # Cache static assets
        location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf)$ {
            expires 1y;
            add_header Cache-Control "public, immutable";
        }
    }

    # API proxy
    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# Backend API (optional separate domain)
server {
    listen 443 ssl http2;
    server_name api.your-domain.com;

    ssl_certificate /etc/ssl/certs/api.crt;
    ssl_certificate_key /etc/ssl/private/api.key;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # CORS headers
        add_header Access-Control-Allow-Origin "https://dmis.your-domain.com";
        add_header Access-Control-Allow-Methods "GET, POST, OPTIONS";
        add_header Access-Control-Allow-Headers "Authorization, Content-Type";
    }
}
```

---

## Deployment Strategy

### Phase 1: Backend Deployment (Day 1)

1. **Deploy API endpoint** (backward compatible)
   ```bash
   # On production server
   cd /var/www/dmis/backend
   git pull origin main
   source venv/bin/activate
   pip install -r requirements.txt
   python manage.py migrate
   python manage.py collectstatic --no-input
   sudo systemctl restart dmis-backend
   ```

2. **Verify endpoint**
   ```bash
   # Test preview-multi endpoint
   curl -X POST https://api.your-domain.com/api/v1/replenishment/needs-list/preview-multi \
     -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '{"event_id": 1, "warehouse_ids": [1], "phase": "BASELINE"}'

   # Should return 200 with warehouse metadata
   ```

3. **Monitor logs**
   ```bash
   tail -f /var/log/dmis/backend.log
   # Watch for errors, slow queries, or 500 responses
   ```

### Phase 2: Frontend Deployment (Day 2-3)

1. **Feature flag enabled for beta users**
   - Add feature flag service to control wizard visibility
   - Deploy frontend with wizard available but not default

2. **Deploy frontend build**
   ```bash
   cd frontend
   ng build --configuration=production
   scp -r dist/frontend/browser/* user@server:/var/www/dmis/
   ```

3. **Enable wizard for specific users**
   ```typescript
   // In feature-flags.service.ts
   isWizardEnabled(): boolean {
     const betaUsers = ['kemar@odpem.gov.jm', 'admin@odpem.gov.jm'];
     const currentUser = this.authService.getCurrentUser().email;
     return betaUsers.includes(currentUser) ||
            localStorage.getItem('dmis_wizard_beta') === 'true';
   }
   ```

4. **Update dashboard to show wizard option**
   ```typescript
   generateNeedsList(): void {
     const useWizard = this.featureFlags.isWizardEnabled();
     const route = useWizard
       ? '/replenishment/needs-list-wizard'
       : '/replenishment/needs-list-preview';

     this.router.navigate([route], { queryParams: { /*...*/ } });
   }
   ```

### Phase 3: Beta Testing (Week 1)

**Beta User Group**: 3-5 key users including Kemar

**Test Scenarios**:
- [ ] Create needs list for single warehouse (baseline)
- [ ] Create needs list for multiple warehouses (new feature)
- [ ] Adjust quantities with reasons
- [ ] Submit for approval
- [ ] Save as draft
- [ ] Test on mobile device (field conditions)
- [ ] Test with slow network (3G simulation)

**Feedback Collection**:
- Daily check-ins with beta users
- Track usage with analytics (page views, completion rate, errors)
- Document any bugs or UX issues

**Success Criteria**:
- 95%+ completion rate (users finish wizard without abandoning)
- < 2% error rate on API calls
- Positive feedback from beta users
- Mobile usability confirmed

### Phase 4: Gradual Rollout (Week 2-4)

**Week 2**: 25% of users
```typescript
isWizardEnabled(): boolean {
  const userId = this.authService.getCurrentUser().id;
  return userId % 4 === 0;  // Every 4th user
}
```

**Week 3**: 50% of users
```typescript
isWizardEnabled(): boolean {
  const userId = this.authService.getCurrentUser().id;
  return userId % 2 === 0;  // Every 2nd user
}
```

**Week 4**: 100% of users
```typescript
isWizardEnabled(): boolean {
  return true;  // All users
}
```

### Phase 5: Full Migration (Week 5-6)

**Update default route**:
```typescript
// Remove feature flag check
generateNeedsList(): void {
  this.router.navigate(['/replenishment/needs-list-wizard'], {
    queryParams: { /*...*/ }
  });
}
```

**Add migration notice to old preview**:
```html
<!-- In needs-list-preview.component.html -->
<div class="migration-banner">
  <mat-icon>info</mat-icon>
  <p>This page will be deprecated on [DATE]. Please use the new
     <a routerLink="/replenishment/needs-list-wizard">Needs List Wizard</a>.</p>
</div>
```

**Deprecation timeline**:
- Week 5: Show banner on old preview
- Week 6: Add redirect timer (10 seconds)
- Week 7: Redirect immediately with option to use old version
- Week 8: Remove old preview route entirely

---

## Monitoring & Rollback

### Key Metrics to Monitor

**Backend Metrics**:
- API response times (target: < 2s for preview-multi)
- Error rates (target: < 2%)
- Database query performance
- Warehouse name resolution cache hits

**Frontend Metrics**:
- Wizard completion rate (target: > 95%)
- Step abandonment rate (where users drop off)
- Time to complete wizard (target: < 5 minutes)
- Mobile vs desktop usage
- Adjustment usage (how often users adjust quantities)

### Analytics Implementation

```typescript
// In wizard steps, track events
export class ScopeStepComponent {
  calculateGaps(): void {
    this.analytics.trackEvent('wizard_step1_complete', {
      warehouse_count: this.form.value.warehouse_ids.length,
      phase: this.form.value.phase
    });

    // ... existing code
  }
}
```

### Rollback Plan

**If error rate > 5% or completion rate < 80%**:

1. **Immediate rollback** (< 5 minutes)
   ```typescript
   // Set feature flag to false
   isWizardEnabled(): boolean {
     return false;  // Emergency rollback
   }

   // Redeploy frontend
   ng build --configuration=production
   ```

2. **Investigate issues**
   - Check backend logs for 500 errors
   - Review frontend console errors
   - Analyze user feedback

3. **Fix and redeploy**
   - Create hotfix branch
   - Test thoroughly
   - Redeploy with monitoring

---

## User Training

### Quick Start Guide

Create `docs/WIZARD_GUIDE.md`:

```markdown
# Needs List Wizard - Quick Start

## Creating a Needs List in 3 Easy Steps

### Step 1: Select Scope
1. Enter Event ID (e.g., Hurricane Ian: 123)
2. Select one or more warehouses from dropdown
3. Confirm event phase (SURGE/STABILIZED/BASELINE)
4. Click "Calculate Gaps"

### Step 2: Review & Adjust
1. Review table showing items, warehouses, and gaps
2. Items highlighted in yellow cannot be fully covered
3. Adjust quantities if needed (reason required)
4. Click "Next" when ready

### Step 3: Submit
1. Review summary (items, units, cost)
2. See who will approve based on phase/value
3. Add optional notes
4. Click "Submit for Approval" or "Save as Draft"

## Tips for Field Use
- Works on mobile! Use in the field during response
- Wizard auto-saves your progress (can close and resume)
- Multi-warehouse selection helps plan regionally
- Uncovered items need special attention
```

### Training Video Script

**Title**: "New Needs List Wizard - 3 Minute Demo"

**Script**:
1. (0:00-0:30) Introduction: "Hi, I'm going to show you the new Needs List Wizard that makes creating supply requests faster and easier."

2. (0:30-1:00) Step 1 Demo: "First, I select the event and warehouses. Notice I can now select multiple warehouses at once - this is great for regional planning."

3. (1:00-2:00) Step 2 Demo: "The system calculated gaps across all selected warehouses. Items in yellow can't be fully covered by our normal sources - these need special attention. I can adjust quantities here with a reason."

4. (2:00-2:45) Step 3 Demo: "Finally, I review the summary, see who will approve, add notes, and submit. The wizard tracked everything I need."

5. (2:45-3:00) Closing: "That's it! The wizard works on mobile too, so you can create needs lists from the field during response operations."

---

## Performance Optimization

### Backend Optimizations

**Database Indexes**:
```sql
-- Speed up warehouse queries
CREATE INDEX idx_needs_list_warehouse ON replenishment_needslist(warehouse_id);
CREATE INDEX idx_needs_list_event ON replenishment_needslist(event_id);

-- Speed up item lookups
CREATE INDEX idx_item_warehouse ON replenishment_needslistitem(item_id, warehouse_id);
```

**Query Optimization**:
```python
# Use select_related to reduce queries
def get_warehouse_name(warehouse_id: int) -> str:
    # Add caching
    cache_key = f'warehouse_name_{warehouse_id}'
    cached = cache.get(cache_key)
    if cached:
        return cached

    # Query and cache for 1 hour
    name = _fetch_warehouse_name(warehouse_id)
    cache.set(cache_key, name, 3600)
    return name
```

### Frontend Optimizations

**Lazy Loading**:
```typescript
// In app.routes.ts
export const routes: Routes = [
  {
    path: 'replenishment/needs-list-wizard',
    loadComponent: () => import('./replenishment/needs-list-wizard/needs-list-wizard.component')
      .then(m => m.NeedsListWizardComponent)
  }
];
```

**Bundle Analysis**:
```bash
# Analyze bundle size
ng build --configuration=production --stats-json
npx webpack-bundle-analyzer dist/frontend/browser/stats.json

# Look for opportunities to:
# - Remove unused dependencies
# - Lazy load large components
# - Tree-shake Material modules
```

**Virtual Scrolling** (if items > 100):
```typescript
// In preview-step.component.html
<cdk-virtual-scroll-viewport itemSize="48" class="preview-table">
  <table mat-table [dataSource]="items">
    <!-- ... columns ... -->
  </table>
</cdk-virtual-scroll-viewport>
```

---

## Security Considerations

### API Security

**Rate Limiting**:
```python
# In Django settings
REST_FRAMEWORK = {
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.UserRateThrottle'
    ],
    'DEFAULT_THROTTLE_RATES': {
        'user': '100/hour'  # Prevent abuse
    }
}
```

**Input Validation**:
```python
def needs_list_preview_multi(request):
    warehouse_ids = request.data.get('warehouse_ids', [])

    # Validate array length (prevent DOS)
    if len(warehouse_ids) > 20:
        return Response({'error': 'Maximum 20 warehouses allowed'}, status=400)

    # Validate integer values
    validated_ids = []
    for wid in warehouse_ids:
        if not isinstance(wid, int) or wid < 1:
            return Response({'error': f'Invalid warehouse_id: {wid}'}, status=400)
        validated_ids.append(wid)
```

### Frontend Security

**XSS Prevention**:
```html
<!-- Angular sanitizes by default, but be explicit -->
<div [innerHTML]="item.notes | sanitize"></div>
```

**CSRF Protection**:
```typescript
// Ensure CSRF token sent with requests
@Injectable()
export class XsrfInterceptor implements HttpInterceptor {
  intercept(req: HttpRequest<any>, next: HttpHandler) {
    const token = this.cookieService.get('csrftoken');
    if (token) {
      req = req.clone({
        setHeaders: { 'X-CSRFToken': token }
      });
    }
    return next.handle(req);
  }
}
```

---

## Troubleshooting

### Common Issues

**Issue**: "warehouse_ids array required" error
**Solution**: Ensure frontend sends array, not single integer
```typescript
// WRONG
warehouse_ids: this.form.value.warehouse_id

// RIGHT
warehouse_ids: this.form.value.warehouse_ids || []
```

**Issue**: Warehouse names showing as "Warehouse 123" instead of actual names
**Solution**: Check legacy database connection and schema name
```python
# Verify in Django shell
from replenishment.services.data_access import get_warehouse_name
print(get_warehouse_name(1))  # Should return actual name
```

**Issue**: Wizard state lost on page refresh
**Solution**: Check localStorage is enabled
```typescript
// Test localStorage
try {
  localStorage.setItem('test', 'test');
  localStorage.removeItem('test');
} catch (e) {
  console.error('localStorage not available:', e);
}
```

**Issue**: Tests failing in production
**Solution**: Ensure test database configured
```bash
# Run tests with SQLite
DJANGO_DEBUG=1 DJANGO_USE_SQLITE=1 python manage.py test
```

---

## Success Criteria

### Launch Criteria (Must meet before 100% rollout)
- [ ] All automated tests passing
- [ ] Beta users report positive experience
- [ ] Error rate < 2%
- [ ] Completion rate > 95%
- [ ] Mobile usability confirmed
- [ ] Performance targets met (< 2s API response)
- [ ] Rollback plan tested
- [ ] User training materials published
- [ ] Monitoring dashboards configured

### Post-Launch Review (30 days after full rollout)
- [ ] Adoption rate > 90%
- [ ] Average completion time reduced by 20%
- [ ] Mobile usage > 30%
- [ ] User satisfaction score > 8/10
- [ ] Zero critical bugs reported
- [ ] Support tickets < 5 per week

---

## Support Contacts

**Technical Issues**:
- Backend: backend-team@dmis.gov.jm
- Frontend: frontend-team@dmis.gov.jm
- Infrastructure: devops@dmis.gov.jm

**User Training**:
- Training Coordinator: training@odpem.gov.jm

**Emergency Rollback**:
- On-Call Engineer: +1-876-XXX-XXXX

---

## Appendix

### A. Environment Variable Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| DJANGO_DEBUG | Yes | 0 | Set to 1 for development |
| DJANGO_SECRET_KEY | Yes | - | Generate secure random key |
| DJANGO_ALLOWED_HOSTS | Yes | - | Comma-separated domain list |
| DB_NAME | Yes | - | PostgreSQL database name |
| DB_USER | Yes | - | PostgreSQL username |
| DB_PASSWORD | Yes | - | PostgreSQL password |
| LEGACY_DB_HOST | No | localhost | Legacy database server |
| DJANGO_USE_SQLITE | No | 0 | Set to 1 for testing only |

### B. API Endpoint Documentation

**POST /api/v1/replenishment/needs-list/preview-multi**

Request:
```json
{
  "event_id": 1,
  "warehouse_ids": [1, 2, 3],
  "phase": "BASELINE",
  "as_of_datetime": "2024-01-15T10:00:00Z"  // optional
}
```

Response:
```json
{
  "event_id": 1,
  "phase": "BASELINE",
  "warehouse_ids": [1, 2, 3],
  "warehouses": [
    {"warehouse_id": 1, "warehouse_name": "Kingston Central"},
    {"warehouse_id": 2, "warehouse_name": "Montego Bay"},
    {"warehouse_id": 3, "warehouse_name": "Spanish Town"}
  ],
  "items": [
    {
      "item_id": 101,
      "item_name": "Water 1L",
      "warehouse_id": 1,
      "warehouse_name": "Kingston Central",
      "available_qty": 500,
      "gap_qty": 200,
      "horizon": {
        "A": {"recommended_qty": 100},
        "B": {"recommended_qty": 50},
        "C": {"recommended_qty": 50}
      },
      // ... other fields
    }
  ],
  "as_of_datetime": "2024-01-15T10:00:00Z"
}
```

### C. Feature Flag Configuration

Create `frontend/src/app/core/services/feature-flags.service.ts`:

```typescript
import { Injectable } from '@angular/core';
import { AuthService } from './auth.service';

@Injectable({ providedIn: 'root' })
export class FeatureFlagsService {
  constructor(private authService: AuthService) {}

  isWizardEnabled(): boolean {
    // Check environment
    if (!environment.enableWizard) {
      return false;
    }

    // Check localStorage override (for testing)
    const override = localStorage.getItem('dmis_force_wizard');
    if (override === 'true') return true;
    if (override === 'false') return false;

    // Check user rollout percentage
    const user = this.authService.getCurrentUser();
    const rolloutPercent = this.getWizardRolloutPercent();

    // Use user ID hash to determine eligibility
    const userHash = this.hashUserId(user.id);
    return userHash < rolloutPercent;
  }

  private getWizardRolloutPercent(): number {
    // Could fetch from API, or use config
    return 100;  // 0-100, represents % of users
  }

  private hashUserId(userId: number): number {
    // Simple hash to distribute users evenly
    return (userId * 2654435761) % 100;
  }
}
```

---

**Document Version**: 1.0
**Last Updated**: 2024-01-15
**Next Review**: 30 days post-launch
