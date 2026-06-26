pipeline {
    agent {
        docker {
            image 'python:3.12-slim'
            args '--user root'
        }
    }

    environment {
        UV_CACHE_DIR       = "${WORKSPACE}/.uv-cache"
        PIP_NO_COLOR       = '1'
        RUFF_NO_CACHE      = '1'
        // GitHub Models token injected from a Jenkins credential named
        // 'github-models-token' (a secret text credential).
        GITHUB_MODELS_TOKEN = credentials('github-models-token')
    }

    options {
        timeout(time: 15, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    stages {
        stage('Setup') {
            steps {
                sh '''
                    pip install --quiet uv
                    uv sync --extra dev --extra server --extra github
                '''
            }
        }

        stage('Lint') {
            steps {
                sh 'uv run ruff check src tests'
            }
        }

        stage('Test') {
            environment {
                DEVOPS_AGENT_LLM_PROVIDER = 'github'
            }
            steps {
                sh 'uv run pytest -q --tb=short'
            }
            post {
                always {
                    junit allowEmptyResults: true, testResults: 'test-results/*.xml'
                }
            }
        }

        stage('Build image') {
            when {
                branch 'main'
            }
            steps {
                sh '''
                    docker build -t devops-agent:${BUILD_NUMBER} .
                    docker tag devops-agent:${BUILD_NUMBER} devops-agent:latest
                '''
            }
        }
    }

    post {
        failure {
            // Notify your ops channel; adapt to Slack/Teams/PagerDuty as needed.
            echo "Pipeline FAILED — check ${BUILD_URL}"
        }
    }
}
