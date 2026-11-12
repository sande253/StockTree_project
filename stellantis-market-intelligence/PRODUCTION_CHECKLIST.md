# Production Deployment Checklist

Complete this checklist before deploying to production.

## Pre-Deployment

### Environment Setup
- [ ] Python 3.11+ installed
- [ ] uv package manager installed
- [ ] All dependencies installed (`uv sync`)
- [ ] `.env` file created and configured
- [ ] Secure `SECRET_KEY` generated
- [ ] `GROQ_API_KEY` configured (if using AI features)
- [ ] Production environment variables set (`FLASK_ENV=production`)

### Database
- [ ] Database directory created (`data/warehouse/`)
- [ ] Companies loaded (`uv run python -m storage.load_companies`)
- [ ] Initial market data ingested
- [ ] Database connection tested
- [ ] Backup strategy implemented

### Data
- [ ] All data directories created (`data/{raw,processed,features,reports,warehouse,vector_store}`)
- [ ] Logs directory created (`logs/`)
- [ ] Proper file permissions set
- [ ] Disk space verified (10GB+ recommended)

### Configuration
- [ ] `config/companies.yaml` reviewed
- [ ] `config/relationships.yaml` populated with evidence
- [ ] `config/event_rules.yaml` thresholds configured
- [ ] `config/benchmarks.yaml` configured

### Security
- [ ] Default `SECRET_KEY` changed
- [ ] Session cookies configured (`SESSION_COOKIE_SECURE=True` for HTTPS)
- [ ] File permissions restricted (database, logs, config)
- [ ] Firewall rules configured
- [ ] Rate limiting configured (reverse proxy)
- [ ] HTTPS/SSL certificates installed (if applicable)
- [ ] Security headers enabled

## Deployment

### Application Server
- [ ] Production WSGI server selected (Gunicorn/Waitress)
- [ ] Worker/thread count configured based on resources
- [ ] Timeout values configured
- [ ] Server configuration tested (`gunicorn.conf.py` or startup script)
- [ ] Application starts successfully
- [ ] Health check endpoint responds (`/api/health`)

### Reverse Proxy (if applicable)
- [ ] Nginx/Apache configured
- [ ] SSL/TLS configured
- [ ] Proxy headers set correctly
- [ ] Static file serving configured
- [ ] Security headers added
- [ ] Rate limiting enabled
- [ ] Timeout values configured

### Monitoring
- [ ] Health check endpoint tested (`/api/health/detailed`)
- [ ] Prometheus metrics endpoint accessible (`/metrics`)
- [ ] Log files rotating correctly
- [ ] Log monitoring configured
- [ ] Disk usage monitoring configured
- [ ] Application metrics dashboard created

### Scheduled Tasks
- [ ] Data ingestion schedule configured (cron/Task Scheduler)
- [ ] Event detection schedule configured
- [ ] Vector index rebuild schedule configured
- [ ] Backup schedule configured
- [ ] Log rotation configured

## Post-Deployment

### Testing
- [ ] All API endpoints tested
- [ ] Dashboard pages accessible
- [ ] Event detection working
- [ ] Relationship graph rendering
- [ ] Report generation working
- [ ] Search functionality working
- [ ] Error handling tested

### Performance
- [ ] Response times acceptable (< 2s for most endpoints)
- [ ] Memory usage stable
- [ ] CPU usage reasonable
- [ ] Database queries optimized
- [ ] Caching working correctly

### Backup & Recovery
- [ ] Database backup tested
- [ ] Config backup tested
- [ ] Backup restore procedure documented
- [ ] Disaster recovery plan documented

### Documentation
- [ ] API documentation accessible
- [ ] Deployment documentation complete
- [ ] Troubleshooting guide available
- [ ] System architecture documented
- [ ] Runbooks created for common issues

### Monitoring Alerts
- [ ] Disk space alerts configured
- [ ] Application error alerts configured
- [ ] Health check alerts configured
- [ ] Performance degradation alerts configured

## Week 1 Post-Deployment

- [ ] Monitor logs daily
- [ ] Check health endpoints daily
- [ ] Verify scheduled tasks running
- [ ] Review performance metrics
- [ ] Collect user feedback
- [ ] Document any issues

## Month 1 Post-Deployment

- [ ] Review security logs
- [ ] Analyze performance trends
- [ ] Optimize slow queries
- [ ] Review and tune caching
- [ ] Update documentation based on learnings
- [ ] Plan capacity upgrades if needed

## Ongoing Maintenance

### Daily
- [ ] Check application health
- [ ] Monitor error logs
- [ ] Verify scheduled tasks completed

### Weekly
- [ ] Review performance metrics
- [ ] Check disk space
- [ ] Review backup success
- [ ] Analyze API usage patterns

### Monthly
- [ ] Update dependencies (`uv sync`)
- [ ] Review security patches
- [ ] Analyze long-term trends
- [ ] Review and optimize database
- [ ] Clean up old logs/data

### Quarterly
- [ ] Full security audit
- [ ] Performance optimization review
- [ ] Disaster recovery drill
- [ ] Capacity planning review
- [ ] Documentation update

## Rollback Plan

If issues occur after deployment:

1. **Immediate Actions:**
   - [ ] Stop new traffic to application
   - [ ] Identify root cause from logs
   - [ ] Assess severity and impact

2. **Rollback Steps:**
   - [ ] Stop application server
   - [ ] Restore previous code version
   - [ ] Restore database backup if needed
   - [ ] Restart application
   - [ ] Verify health checks pass

3. **Communication:**
   - [ ] Notify stakeholders
   - [ ] Document issue and resolution
   - [ ] Schedule post-mortem

## Emergency Contacts

```
Application Owner: ___________________
Database Admin: ___________________
Infrastructure Team: ___________________
On-Call Support: ___________________
```

## Sign-Off

Deployment approved by:

- [ ] Technical Lead: ____________ Date: ______
- [ ] Security Lead: ____________ Date: ______
- [ ] Operations Lead: ____________ Date: ______
- [ ] Product Owner: ____________ Date: ______

## Notes

Record any deviations from the standard deployment process:

```
_________________________________________________________
_________________________________________________________
_________________________________________________________
```
