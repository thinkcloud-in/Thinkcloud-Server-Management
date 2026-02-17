pipeline {
    agent any

    environment {
        APP_NAME       = "server_management"
        IMAGE_TAG      = "latest"

        WORKDIR        = "/home/admin-01/Desktop/rcv/server-management"
        TAR_DIR        = "/home/admin-01/Desktop/rcv/tar"
        TAR_FILE       = "server_management_latest.tar"

        REMOTE_HOST    = "172.16.0.101"
        REMOTE_USER    = "root"
        REMOTE_TAR_DIR = "/home/rcv/daas_installer/daas_tar"
        REMOTE_BASE_DIR = "/home/rcv/daas_installer/daas_v1/server-management"
        SCRIPT_DIR     = "/home/rcv/Desktop/scrpit"
        SSH_KEY        = "/root/.ssh/id_ed25519" // mounted inside Jenkins container
    }

    stages {

        stage('Prepare Directories') {
            steps {
                sh 'mkdir -p ${TAR_DIR}'
            }
        }

        stage('Checkout Code') {
            steps {
                dir("${WORKDIR}") {
                    deleteDir()
                    git branch: 'dynamic-data',
                        url: 'https://github.com/thinkcloud-in/Thinkcloud-Server-Management.git',
                        credentialsId: 'github_token'
                }
            }
        }

        stage('Build Docker Image') {
            steps {
                dir("${WORKDIR}") {
                    sh '''docker image prune -a -f
                    docker build -t ${APP_NAME}:${IMAGE_TAG} .'''
                }
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

        stage('Copy TAR to Remote Server') {
            steps {
                sh '''
                    # Create remote directory
                    ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no \
                        ${REMOTE_USER}@${REMOTE_HOST} "mkdir -p ${REMOTE_TAR_DIR}"

                    # Copy TAR file
                    scp -i ${SSH_KEY} -o StrictHostKeyChecking=no \
                        ${TAR_DIR}/${TAR_FILE} \
                        ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_TAR_DIR}/
                    
                    # Copy Kubernetes YAML files (from repo) to BASE_DIR
                    scp -i ${SSH_KEY} -o StrictHostKeyChecking=no \
                        ${WORKDIR}/k8s/*.yaml \
                        ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_BASE_DIR}/
                '''
            }
        }

        stage('Deploy on Remote Server') {
            steps {
                sh """
                echo "➡️ Running server-management deployment script on remote server..."
                ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no ${REMOTE_USER}@${REMOTE_HOST} bash -s <<ENDSSH
                    /home/rcv/Desktop/scrpit/server-management.sh
ENDSSH
                """
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
