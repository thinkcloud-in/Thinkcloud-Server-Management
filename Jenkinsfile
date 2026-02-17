pipeline {
    agent any

    environment {
        APP_NAME       = "server_management"
        IMAGE_TAG      = "latest"

        TAR_DIR        = "${WORKSPACE}/tar"
        TAR_FILE       = "server_management_latest.tar"

        REMOTE_HOST    = "172.16.0.101"
        REMOTE_USER    = "root"
        REMOTE_TAR_DIR = "/home/rcv/daas_installer/daas_tar"
        REMOTE_BASE_DIR = "/home/rcv/daas_installer"
        SSH_KEY        = "/root/.ssh/id_ed25519"
    }

    stages {

        stage('Prepare Directories') {
            steps {
                sh 'mkdir -p ${TAR_DIR}'
            }
        }

        stage('Checkout Code') {
            steps {
                deleteDir()
                git branch: 'dynamic-data',
                    url: 'https://github.com/thinkcloud-in/Thinkcloud-Server-Management.git',
                    credentialsId: 'github_token'
            }
        }

        stage('Build Docker Image') {
            steps {
                sh '''
                docker image prune -a -f
                docker build -t ${APP_NAME}:${IMAGE_TAG} .
                '''
            }
        }

        stage('Save Docker Image as TAR') {
            steps {
                sh '''
                docker save -o ${TAR_DIR}/${TAR_FILE} ${APP_NAME}:${IMAGE_TAG}
                ls -lh ${TAR_DIR}
                '''
            }
        }

        stage('Copy TAR + YAML to Remote Server') {
            steps {
                sh '''
                # Create remote directories
                ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no \
                    ${REMOTE_USER}@${REMOTE_HOST} "mkdir -p ${REMOTE_TAR_DIR} ${REMOTE_BASE_DIR}"

                # Copy TAR
                scp -i ${SSH_KEY} -o StrictHostKeyChecking=no \
                    ${TAR_DIR}/${TAR_FILE} \
                    ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_TAR_DIR}/

                # Copy Kubernetes YAML
                scp -i ${SSH_KEY} -o StrictHostKeyChecking=no \
                    k8s/*.yaml \
                    ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_BASE_DIR}/
                '''
            }
        }

        stage('Deploy on Remote Server') {
            steps {
                sh '''
                ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no ${REMOTE_USER}@${REMOTE_HOST} << 'EOF'
                    docker load -i /home/rcv/daas_installer/daas_tar/server_management_latest.tar
                    kubectl apply -f /home/rcv/daas_installer/
                EOF
                '''
            }
        }
    }

    post {
        success {
            echo '✅ Build → TAR → Copy → Deploy Successful!'
        }
        failure {
            echo '❌ Pipeline Failed!'
        }
    }
}
