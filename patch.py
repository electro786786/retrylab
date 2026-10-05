with open('zoo/app/main.py', 'r') as f:
    content = f.read()

content = content.replace(
    '''        print('Saving premature response. Existing:', existing)
        await db.commit()  # IMPORTANT: commit the cache before crashing!''',
    '''        print('Saving premature response.')
        await db.commit()  # IMPORTANT: commit the cache before crashing!'''
)

with open('zoo/app/main.py', 'w') as f:
    f.write(content)
