# Slack Integration Guide

This guide explains how to set up Slack notifications for TrakBridge CI/CD pipeline deployments and security alerts.

## 🚀 Quick Setup

### 1. Create Slack Webhook

1. Go to your Slack workspace
2. Navigate to **Apps** → **Custom Integrations** → **Incoming Webhooks**
3. Click **Add to Slack**
4. Choose the channel where you want notifications (e.g., `#deployments`, `#alerts`)
5. Copy the webhook URL (e.g., `https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX`)

### 2. Configure GitHub Secrets

Add the webhook URL to your GitHub repository secrets:

1. Go to your GitHub repository
2. Navigate to **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Name: `SLACK_WEBHOOK_URL`
5. Value: Your Slack webhook URL

### 3. Test the Setup

Trigger a workflow to test Slack notifications:

```bash
# Trigger a manual deployment
gh workflow run "TrakBridge CI/CD Pipeline" \
  --ref main \
  -f environment=development \
  -f deploy=true
```

## 📋 Notification Types

### Development Deployment Notifications

**Success Notification:**
```
🚀 TrakBridge Development Deployed

Environment: Development
Commit: abc123ef
Branch: develop
URL: http://localhost:5000
Login: admin / TrakBridge-Setup-2025!

Ready for testing! 🎉
```

**Failure Notification:**
```
❌ TrakBridge Development Deployment Failed

Environment: Development
Commit: abc123ef
Branch: develop
Error: Deployment failed - check logs
```

### Staging Deployment Notifications

**Success Notification:**
```
🔄 TrakBridge Staging Deployed

Environment: Staging
Version: v1.2.3-rc1
Commit: abc123ef
URL: http://localhost

Ready for UAT and final validation before production! 🧪
```

### Production Release Notifications

**Success Notification:**
```
🎉 TrakBridge Production Release

Version: v1.2.3
Docker Hub: emfoursolutions/trakbridge:v1.2.3
Platforms: linux/amd64, linux/arm64
Commit: abc123ef

Production release is now available! 🚀
```

**Failure Notification:**
```
❌ TrakBridge Production Release Failed

Version: v1.2.3
Commit: abc123ef
Error: Production release failed - check logs
```

### Security Scan Notifications

**Security Scan Results:**
```
🔒 TrakBridge Security Scan Complete

Scan Results:
- Static Analysis: ✅ Passed
- Security Tests: ✅ Passed
- Dependencies: ✅ Passed
- Docker: ✅ Passed

Check GitHub Actions for detailed results.
```

## 🔧 Configuration Options

### Channel-Specific Notifications

You can set up different webhooks for different types of notifications:

```yaml
# In GitHub Actions workflow
- name: Notify Slack - Development
  uses: 8398a7/action-slack@v3
  with:
    webhook_url: ${{ secrets.SLACK_WEBHOOK_DEV }}  # #dev-deployments

- name: Notify Slack - Production  
  uses: 8398a7/action-slack@v3
  with:
    webhook_url: ${{ secrets.SLACK_WEBHOOK_PROD }}  # #production-alerts
```

### Custom Message Templates

Customize notification messages by modifying the workflow:

```yaml
- name: Custom Slack Notification
  uses: 8398a7/action-slack@v3
  with:
    status: ${{ job.status }}
    title: "🚀 Custom Title"
    message: |
      **Environment:** ${{ github.event.inputs.environment }}
      **Triggered by:** ${{ github.actor }}
      **Commit:** ${{ github.sha }}
      **Time:** ${{ github.event.head_commit.timestamp }}
    webhook_url: ${{ secrets.SLACK_WEBHOOK_URL }}
```

### Conditional Notifications

Only send notifications for specific conditions:

```yaml
- name: Notify on failure only
  if: failure()
  uses: 8398a7/action-slack@v3
  with:
    status: failure
    title: "❌ Deployment Failed"
    webhook_url: ${{ secrets.SLACK_WEBHOOK_URL }}

- name: Notify on production only
  if: github.ref == 'refs/heads/main'
  uses: 8398a7/action-slack@v3
  with:
    status: success
    title: "🎉 Production Deployment"
    webhook_url: ${{ secrets.SLACK_WEBHOOK_URL }}
```

## 📱 Advanced Slack Features

### Rich Message Formatting

Use Slack's Block Kit for rich messages:

```yaml
- name: Rich Slack Notification
  uses: 8398a7/action-slack@v3
  with:
    status: success
    fields: repo,message,commit,author,action,eventName,ref,workflow
    title: "TrakBridge Deployment"
    color: good
    webhook_url: ${{ secrets.SLACK_WEBHOOK_URL }}
```

### User/Channel Mentions

Mention specific users or channels in notifications:

```yaml
message: |
  <!channel> TrakBridge production deployment complete!
  @here Please validate the deployment.
  <@U1234567890> Your feature is now live!
```

### Thread Notifications

Keep related notifications in threads:

```yaml
- name: Start deployment thread
  id: slack
  uses: 8398a7/action-slack@v3
  with:
    status: custom
    custom_payload: |
      {
        "text": "🚀 Starting TrakBridge deployment...",
        "channel": "#deployments"
      }
    webhook_url: ${{ secrets.SLACK_WEBHOOK_URL }}

- name: Update thread with result
  uses: 8398a7/action-slack@v3
  with:
    status: success
    custom_payload: |
      {
        "text": "✅ Deployment completed successfully!",
        "channel": "#deployments",
        "thread_ts": "${{ steps.slack.outputs.ts }}"
      }
    webhook_url: ${{ secrets.SLACK_WEBHOOK_URL }}
```

## 🛠️ Troubleshooting

### Common Issues

**1. Webhook URL not working:**
- Verify the webhook URL is correct
- Check if the Slack app is still active
- Ensure the webhook has permission to post to the channel

**2. Messages not appearing:**
- Check the channel permissions
- Verify the webhook is configured for the correct channel
- Test the webhook manually with curl:

```bash
curl -X POST -H 'Content-type: application/json' \
  --data '{"text":"Test message"}' \
  YOUR_WEBHOOK_URL
```

**3. GitHub secret not found:**
- Verify the secret name matches exactly (`SLACK_WEBHOOK_URL`)
- Check if the secret is available in the repository/organization
- Ensure the workflow has access to the secret

### Testing Webhooks

Test your webhook configuration manually:

```bash
# Test webhook
curl -X POST -H 'Content-type: application/json' \
  --data '{
    "text": "🧪 Testing TrakBridge Slack integration",
    "username": "TrakBridge CI/CD",
    "icon_emoji": ":rocket:"
  }' \
  $SLACK_WEBHOOK_URL
```

### Debugging GitHub Actions

Enable debug logging for Slack notifications:

```yaml
- name: Debug Slack notification
  uses: 8398a7/action-slack@v3
  env:
    SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  with:
    status: success
    title: "Debug notification"
    webhook_url: ${{ secrets.SLACK_WEBHOOK_URL }}
```

## 📊 Notification Examples

### Development Environment Ready

```json
{
  "text": "🚀 TrakBridge Development Environment Ready",
  "blocks": [
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*TrakBridge Development Deployed* :rocket:"
      }
    },
    {
      "type": "section",
      "fields": [
        {
          "type": "mrkdwn",
          "text": "*Environment:*\nDevelopment"
        },
        {
          "type": "mrkdwn",
          "text": "*URL:*\n<http://localhost:5000|Access Application>"
        },
        {
          "type": "mrkdwn",
          "text": "*Login:*\nadmin / TrakBridge-Setup-2025!"
        },
        {
          "type": "mrkdwn",
          "text": "*Branch:*\ndevelop"
        }
      ]
    },
    {
      "type": "actions",
      "elements": [
        {
          "type": "button",
          "text": {
            "type": "plain_text",
            "text": "View Logs"
          },
          "url": "https://github.com/emfoursolutions/trakbridge/actions"
        },
        {
          "type": "button",
          "text": {
            "type": "plain_text",
            "text": "Test Application"
          },
          "url": "http://localhost:5000"
        }
      ]
    }
  ]
}
```

### Security Alert

```json
{
  "text": "🔒 TrakBridge Security Scan Alert",
  "blocks": [
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*Security Scan Alert* :warning:"
      }
    },
    {
      "type": "section",
      "fields": [
        {
          "type": "mrkdwn",
          "text": "*Critical Issues:*\n2"
        },
        {
          "type": "mrkdwn",
          "text": "*High Issues:*\n5"
        },
        {
          "type": "mrkdwn",
          "text": "*Scan Type:*\nFull Security Scan"
        },
        {
          "type": "mrkdwn",
          "text": "*Branch:*\nmain"
        }
      ]
    },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "<!channel> *Action Required:* Critical security vulnerabilities found. Please review and fix immediately."
      }
    }
  ]
}
```

## 🎯 Best Practices

### 1. Channel Organization
- **#deployments**: All deployment notifications
- **#security-alerts**: Security scan results and alerts
- **#dev-notifications**: Development environment updates
- **#production-alerts**: Production releases and critical alerts

### 2. Message Content
- Include relevant information (environment, version, commit)
- Use emojis for quick visual identification
- Provide direct links to logs and applications
- Include login credentials for development environments

### 3. Notification Frequency
- Only notify on significant events (deployments, security issues)
- Avoid spamming channels with too many notifications
- Use threading for related updates
- Consider time zones for critical notifications

### 4. Security Considerations
- Don't include sensitive information in messages
- Use secure channels for production alerts
- Limit webhook access to necessary team members
- Rotate webhook URLs periodically

---

*For additional support, see the [GitHub Actions documentation](https://docs.github.com/en/actions) and [Slack API documentation](https://api.slack.com/).*