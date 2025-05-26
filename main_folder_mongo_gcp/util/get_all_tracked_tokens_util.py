import storage.users as users
from typing import Union

def get_all_tracked_tokens(user_id: Union[str, int]) -> list[str]:
    user_id = str(user_id)
    user_chains = users.USER_TRACKING.get(user_id, {})
    return [addr for chain_tokens in user_chains.values() for addr in chain_tokens]
