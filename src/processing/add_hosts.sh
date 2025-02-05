#!/bin/bash
input=$1
i=1
while IFS= read -r line
do
    ssh-keyscan -p $2 -H $line >> ~/.ssh/known_hosts
done < "$input"
