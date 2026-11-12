"""Keep action results visible after Streamlit reruns."""
import streamlit as st


def scoped_selectbox(label, options, *, key, host=None, **kwargs):
    """Keep a stable model alias but give each platform its own browser widget ID.

    Removing session_state[key] alone does not reset Streamlit's mounted React
    select label. Cross-page navigation writes the alias before rendering.
    """
    platform=st.session_state.get('active_platform')
    if not platform:
        return (host or st).selectbox(label,options,key=key,**kwargs)
    widget_key=key+'__'+platform
    synced=key+'__synced'
    if key in st.session_state and st.session_state[key] in options:
        if st.session_state.get(synced)!=st.session_state[key] or widget_key not in st.session_state:
            st.session_state[widget_key]=st.session_state[key]
    if widget_key in st.session_state and st.session_state[widget_key] not in options:
        index=kwargs.get('index',0)
        # Explicitly send a new value to the mounted browser control. Deleting
        # the server key alone can leave its previous label on screen.
        st.session_state[widget_key]=options[index] if options and index is not None else None
    if widget_key in st.session_state and 'index' in kwargs:kwargs['index']=None
    value=(host or st).selectbox(label,options,key=widget_key,**kwargs)
    st.session_state[key]=value
    st.session_state[synced]=value
    return value


def notify(message, level='success'):
    st.session_state.setdefault('_clab_notices', []).append((level, str(message)))


def show_notices():
    for level, message in st.session_state.pop('_clab_notices', []):
        getattr(st, level if level in ('success', 'info', 'warning', 'error') else 'info')(message)


def reset_platform_state(platform):
    """Clear dependent selections before any widgets are constructed."""
    old = st.session_state.get('_clab_platform')
    if old is not None and old != platform:
        prefixes = ('hero_', 'quick_', 'library_', 'report_', 'weekly_', 'genre_',
                    'work_', 'peer_', 'challenge_', 'analysis_', 'manual_', 'dy_target_', 'capture_', 'assistant_', 'video_check_', 'material_', 'frames_', 'settings_import_', 'first_import_')
        exact = {'battle_mode', '_battle_selected_work', 'demo_platform', 'link_post'}
        for key in list(st.session_state):
            if key in exact or key.startswith(prefixes):
                del st.session_state[key]
    st.session_state['_clab_platform'] = platform
