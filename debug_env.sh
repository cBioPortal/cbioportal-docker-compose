#!/usr/bin/env bash

# This runs Diagnostic checks for environment setup and logs

check_file_permissions() {
    echo " Checking file permissions..."
    find . -name "*.sh" ! -perm /a+x && {
        echo " Missing execute permissions:"
        find . -name "*.sh" ! -perm /a+x | xargs ls -l 
        return 1
    }
}

check_line_endings() {
    echo " Checking line endings..."
    find . -name "*.sh" -exec file {} \; | grep CRLF && {
        echo " CRLF line endings detected:"
        find . -name "*.sh" -exec file {} \; | grep CRLF | cut -d: -f1 | xargs dos2unix 
        return 1
    }
}

main() {
    echo "=== Starting Environment Diagnostics ==="
    
    # this is for System info checks
    echo "## Platform Info ##"
    uname -a
    
    # this is for File system checks
    check_file_permissions || exit 1 
    check_line_endings || exit 1
    
    
    ./init.sh || {
        echo " Initialization failed. Check logs."
        exit 1 
    }

    echo " All diagnostics passed successfully."
}

main | tee debug.log 
